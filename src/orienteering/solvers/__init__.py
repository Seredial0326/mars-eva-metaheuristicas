"""
Orienteering solvers. Every solver is solve(problem: Problem) -> Solution.
    dp      : exact bitmask DP, up to 20 nodes
    brute   : exact enumeration, up to 8 nodes (validation only)
    cpsat   : OR-Tools CP-SAT, exact model; proves the optimum within its time limit or
              returns its best tour with an upper bound (Solution.bound, .optimal)
    routing : OR-Tools routing with guided local search, heuristic (kept for comparison)
    ils     : iterated local search, heuristic (E6)
    sa      : simulated annealing, heuristic, seeded (E6)
    aco     : ant colony system, heuristic, seeded (E6)
    ga      : genetic algorithm, heuristic, seeded (E6)
The OR-Tools solvers need the ortools package and import it only when used.
"""
from orienteering.solvers import aco, brute, cpsat, dp, ga, ils, routing, sa

SOLVERS = {
    "dp": dp.solve,
    "brute": brute.solve,
    "cpsat": cpsat.solve,
    "routing": routing.solve,
    "ils": ils.solve,
    "sa": sa.solve,
    "aco": aco.solve,
    "ga": ga.solve,
}

MAX_STATIONS = {
    "dp": dp.MAX_STATIONS,
    "brute": brute.MAX_STATIONS,
    "cpsat": cpsat.MAX_STATIONS,
    "routing": routing.MAX_STATIONS,
    "ils": ils.MAX_STATIONS,
    "sa": sa.MAX_STATIONS,
    "aco": aco.MAX_STATIONS,
    "ga": ga.MAX_STATIONS,
}

EXACT = {"dp", "brute"}


"""
Name of the solver to use for n nodes: the DP when it fits, CP-SAT otherwise.
"""
def pick(n):
    return "dp" if n <= dp.MAX_STATIONS else "cpsat"
