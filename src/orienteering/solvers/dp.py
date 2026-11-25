"""
Exact bitmask DP for small orienteering instances (up to 20 stations).
"""
import time
from itertools import islice

from orienteering.problem import Solution, evaluate_route

MAX_STATIONS = 20


"""
Bitmask DP to solve small instances of the orienteering problem (18-20 nodes).
Uses problem.energy, problem.prize, problem.budget, problem.start, problem.end and,
if given, problem.service_j: the service energy of a station is paid when the route
arrives at it (the start's when the route begins), so walking plus service must fit
in the budget.
By default it traces a path starting and ending in node 0. If end != start,
end is always the last stop.
With time windows or a maximum duration (problem.timed) the states keep Pareto labels
(see closable_timed). Among tours with the same prize, the one using less energy wins.
"""
def solve(problem, trace=None):
    return solve_many(problem, [problem.prize], trace=trace)[0]


"""
Solves the same problem for several prize vectors (e.g. scoring rubrics) at once.
Which station sets can be visited within the limits does not depend on the prizes,
so the DP tables are built once and only the choice of the best set is repeated:
for each prize vector, the closable set with the highest prize (ties: least energy).
Returns one Solution per prize vector; runtime_s is the total time of the call and
iterations the number of masks processed.
With `trace` (a Tracer; it never changes the result) the first prize vector is followed:
about 100 progress rows (iter, best_prize, best_energy_j, masks_done, states, closable)
and, at the end, one row per set size k = 1..n (k, states_k, closable_k, best_prize_k);
every row has the same columns, those that do not apply are None.
"""
def solve_many(problem, prizes, trace=None):
    t0 = time.perf_counter()
    if trace is not None:
        trace.start()
    n = problem.n
    if n > MAX_STATIONS:
        raise ValueError(f"the bitmask DP supports up to {MAX_STATIONS} stations, got {n}")
    if problem.timed and problem.time is None:
        raise ValueError("time windows and max_duration_s need problem.time")

    first_mask_prize = progress = None
    if trace is not None:
        first_mask_prize = prizes_by_mask([float(v) for v in prizes[0]], n)
        progress = progress_recorder(problem, first_mask_prize, trace)
    closable, rebuild = (closable_timed(problem, progress) if problem.timed
                         else closable_fast(problem, progress))
    start, end = problem.start, problem.end
    if trace is not None:
        states_by_k_rows(problem, closable, rebuild, first_mask_prize, trace)

    chosen = []
    for idx, prize in enumerate(prizes):
        prize = [float(v) for v in prize]
        if idx == 0 and first_mask_prize is not None:
            mask_prize = first_mask_prize
        else:
            mask_prize = prizes_by_mask(prize, n)
        end_prize = prize[end] if end != start else 0.0
        best = None
        for mask, (spent, finish, state) in closable.items():
            key = (mask_prize[mask] + end_prize, -spent)
            if best is None or key > best[0]:
                best = (key, spent, finish, state)
        chosen.append(best)

    runtime = time.perf_counter() - t0
    solutions = []
    for best in chosen:
        if best is None:
            solutions.append(Solution([], 0.0, 0.0, "dp", runtime, None, iterations=(1 << n) - 1))
            continue
        (total, _), spent, finish, state = best
        route = rebuild(state)
        if finish is None:
            finish = evaluate_route(problem, route)["duration"]
        solutions.append(Solution(route, total, spent, "dp", runtime, finish,
                                  iterations=(1 << n) - 1))
    if trace is not None:
        trace.flush()
    return solutions


"""
Builds the progress callback closable_* call every few masks: it follows the best prize
among the closable sets looking only at the sets added since the last call, and emits one
row. Values of existing sets can only improve in energy, which is read at emit time
(ties on the prize: least energy).
"""
def progress_recorder(problem, mask_prize, trace):
    end_prize = float(problem.prize[problem.end]) if problem.end != problem.start else 0.0
    seen, best, tied = 0, None, []

    def progress(masks_done, states, closable):
        nonlocal seen, best, tied
        for mask in islice(closable, seen, None):
            p = mask_prize[mask]
            if best is None or p > best:
                best, tied = p, [mask]
            elif p == best:
                tied.append(mask)
        seen = len(closable)
        trace(iter=masks_done, best_prize=0.0 if best is None else best + end_prize,
              best_energy_j=min(closable[m][0] for m in tied) if tied else None,
              masks_done=masks_done, states=states, closable=len(closable),
              k=None, states_k=None, closable_k=None, best_prize_k=None)
    return progress


"""
Final pass: one row per set size k with the entries of the DP table (and of the closable
sets) of that size. The overall best is taken from the last progress row.
"""
def states_by_k_rows(problem, closable, rebuild, mask_prize, trace):
    n = problem.n
    states_k, closable_k, best_k = [0] * (n + 1), [0] * (n + 1), [0.0] * (n + 1)
    for mask, count in rebuild.state_counts():
        states_k[mask.bit_count()] += count
    for mask in closable:
        k = mask.bit_count()
        closable_k[k] += 1
        best_k[k] = max(best_k[k], mask_prize[mask])
    last = trace.rows[-1] if trace.rows else {}
    for k in range(1, n + 1):
        trace(iter=(1 << n) - 1, best_prize=last.get("best_prize"),
              best_energy_j=last.get("best_energy_j"), masks_done=None, states=None,
              closable=None, k=k, states_k=states_k[k], closable_k=closable_k[k],
              best_prize_k=best_k[k])


"""
Prize collected by each mask: the mask without its lowest bit plus that bit's station.
"""
def prizes_by_mask(prize, n):
    mask_prize = [0.0] * (1 << n)
    for mask in range(1, 1 << n):
        low = mask & -mask
        mask_prize[mask] = mask_prize[mask ^ low] + prize[low.bit_length() - 1]
    return mask_prize


"""
Energy-only DP. dp[mask][i] = least energy to visit (and serve) the set `mask` ending
at station i. Returns (closable, rebuild): closable maps each set that can be closed
within the budget (leg back to the end included) to (energy, None, state) with its
least-energy closing; rebuild(state) gives the route (rebuild.state_counts() yields
(mask, reachable entries) pairs for the trace).
progress, if given, is called as progress(masks_done, states, closable) about every
2^n / 100 masks and once at the end; states counts the (mask, i) entries reached so far.
"""
def closable_fast(problem, progress=None):
    n = problem.n
    INF = float('inf')
    svc = [float(v) for v in problem.service_j] if problem.service_j is not None else [0.0] * n
    dis = [[float(d) + svc[j] for j, d in enumerate(row)] for row in problem.energy]
    cost, start, end = problem.budget, problem.start, problem.end

    # Closing leg i -> end: the end is served unless it is the start again
    close = [float(problem.energy[i][end]) + (svc[end] if end != start else 0.0) for i in range(n)]

    # n columns, 2^n rows; dp[mask][i] = least cost to visit (and serve) mask finishing at i
    dp = [[INF] * n for _ in range(1 << n)]
    parent = [[-1] * n for _ in range(1 << n)]
    dp[1 << start][start] = svc[start]
    closable = {}
    states = 1
    step = max(1, (1 << n) // 100)

    for mask in range(1, 1 << n):
        if progress is not None and mask % step == 0:
            progress(mask, states, closable)
        if not mask & (1 << start):
            continue
        for i in range(n):
            c = dp[mask][i]

            # If node is unreachable, skip it
            if c == INF:
                continue

            # If the route can close here within cost, remember the cheapest closing of this set
            spent = c + close[i]
            if spent <= cost and (mask not in closable or spent < closable[mask][0]):
                closable[mask] = (spent, None, (mask, i))

            # Update dp values for each station not yet in the mask
            for j in range(n):
                bit = 1 << j
                if mask & bit or (j == end and end != start):
                    continue
                new = c + dis[i][j]
                if new <= cost and new < dp[mask | bit][j]:
                    if dp[mask | bit][j] == INF:
                        states += 1
                    dp[mask | bit][j] = new
                    parent[mask | bit][j] = i

    def rebuild(state):
        mask, i = state
        route = []
        while i != -1:
            route.append(i)
            mask, i = mask ^ (1 << i), parent[mask][i]
        route.reverse()
        route.append(end)
        return route

    def state_counts():
        for mask in range(1, 1 << n):
            yield mask, sum(1 for c in dp[mask] if c != INF)

    rebuild.state_counts = state_counts
    if progress is not None:
        progress((1 << n) - 1, states, closable)
    return closable, rebuild


"""
Same DP with time windows and a maximum duration. With two resources (energy and
time) one value per (mask, i) is no longer enough: a route that spends more energy
but arrives earlier can still be the only one that meets a later window. So each
state keeps its Pareto labels (see add_label). A label is (energy, departure time,
previous station, index of the previous label).
Arriving before a window opens means waiting until it opens (at problem.wait_power_w);
the service then starts and must start no later than the window closes.
Returns (closable, rebuild) like closable_fast, with the finishing time of each closing.
progress is called like in closable_fast; states counts the labels created so far.
"""
def closable_timed(problem, progress=None):
    n = problem.n
    INF = float('inf')
    svc = [float(v) for v in problem.service_j] if problem.service_j is not None else [0.0] * n
    svc_s = [float(v) for v in problem.service_s] if problem.service_s is not None else [0.0] * n
    dis = [[float(d) + svc[j] for j, d in enumerate(row)] for row in problem.energy]
    tim = [[float(t) for t in row] for row in problem.time]
    if problem.windows is not None:
        opens = [float(w[0]) for w in problem.windows]
        closes = [float(w[1]) for w in problem.windows]
    else:
        opens, closes = [0.0] * n, [INF] * n
    max_t = problem.max_duration_s if problem.max_duration_s is not None else INF
    wp = float(problem.wait_power_w)
    cost, start, end = problem.budget, problem.start, problem.end

    labels = [dict() for _ in range(1 << n)]
    closable = {}
    begin0 = max(0.0, opens[start])
    e0 = svc[start] + wp * begin0
    if begin0 <= closes[start] and e0 <= cost:
        labels[1 << start][start] = [(e0, begin0 + svc_s[start], -1, -1)]
    states = len(labels[1 << start])
    step = max(1, (1 << n) // 100)

    for mask in range(1, 1 << n):
        if progress is not None and mask % step == 0:
            progress(mask, states, closable)
        if not mask & (1 << start):
            continue
        for i, here in labels[mask].items():
            for li, (c, t, _, _) in enumerate(here):

                # If the route can close here within energy, windows and duration, remember the cheapest closing
                finish = close_route(i, c, t, start, end, problem.energy, svc, svc_s, tim,
                                     opens, closes, max_t, wp)
                if finish is not None and finish[0] <= cost and (
                        mask not in closable or finish[0] < closable[mask][0]):
                    closable[mask] = (finish[0], finish[1], (mask, i, li))

                # Extend the label to each station not yet in the mask
                for j in range(n):
                    bit = 1 << j
                    if mask & bit or (j == end and end != start):
                        continue
                    arrive = t + tim[i][j]
                    begin = max(arrive, opens[j])
                    new = c + dis[i][j] + wp * (begin - arrive)
                    depart = begin + svc_s[j]
                    if new > cost or begin > closes[j] or depart > max_t:
                        continue
                    if add_label(labels[mask | bit], j, (new, depart, i, li), wp):
                        states += 1

    def rebuild(state):
        mask, i, li = state
        route = []
        while i != -1:
            route.append(i)
            _, _, prev, prev_li = labels[mask][i][li]
            mask, i, li = mask ^ (1 << i), prev, prev_li
        route.reverse()
        route.append(end)
        return route

    def state_counts():
        for mask in range(1, 1 << n):
            yield mask, sum(len(ls) for ls in labels[mask].values())

    rebuild.state_counts = state_counts
    if progress is not None:
        progress((1 << n) - 1, states, closable)
    return closable, rebuild


"""
Energy and finishing time of closing the route from station i (label energy c,
departure t) to end, or None if a window or the maximum duration is broken.
Waiting for the end's window costs wp per second.
"""
def close_route(i, c, t, start, end, energy, svc, svc_s, tim, opens, closes, max_t, wp=0.0):
    arrive = t + tim[i][end]
    if end == start:
        if arrive > closes[end] or arrive > max_t:
            return None
        return c + float(energy[i][end]), arrive
    begin = max(arrive, opens[end])
    finish = begin + svc_s[end]
    if begin > closes[end] or finish > max_t:
        return None
    return c + float(energy[i][end]) + svc[end] + wp * (begin - arrive), finish


"""
Adds a label to state[j] unless another label already dominates it; drops the labels
the new one dominates. Label A (e1, t1) dominates B (e2, t2) when t1 <= t2 and
e1 + wp * (t2 - t1) <= e2: A could wait until t2 at power wp and still spend no more
than B, so anything B can do afterwards A can do as cheaply (with wp = 0 this is
plain Pareto dominance on energy and time). Returns True if the label was added. Only states of larger masks change here,
and their labels are not referenced yet, so indices stay valid.
"""
def add_label(state, j, label, wp=0.0):
    current = state.get(j)
    if current is None:
        state[j] = [label]
        return True
    e, t = label[0], label[1]
    for e2, t2, _, _ in current:
        if t2 <= t and e2 + wp * (t - t2) <= e:
            return False
    state[j] = [lab for lab in current
                if not (t <= lab[1] and e + wp * (lab[1] - t) <= lab[0])] + [label]
    return True
