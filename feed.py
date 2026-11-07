from collections import Counter
from random import Random

CLASS_LABELS = {"loops_only": "L", "hybrid_loops_to_terminal": "L", "terminal_primary": "T"}
CLIPS_PER_LABEL = {"L": 6, "T": 6}
TRANSITION_GOALS = {("L", "L"): 15, ("T", "L"): 15, ("L", "T"): 15, ("T", "T"): 15}


def assign_feed(stimuli, assigned_counts, rng):
    """Score random L/T orders, then sample distinct clips for the chosen order."""
    pools = {label: [] for label in CLIPS_PER_LABEL}
    for stimulus in stimuli:
        pools[CLASS_LABELS[stimulus["payoff_label"]]].append(stimulus)

    order = [label for label, count in CLIPS_PER_LABEL.items() for _ in range(count)]
    remaining = {
        pair: max(0, goal - assigned_counts[pair])
        for pair, goal in TRANSITION_GOALS.items()
    }
    if any(remaining.values()):
        best_orders, best_score = [], -1
        for _ in range(50_000):
            rng.shuffle(order)
            pairs = Counter(zip(order, order[1:]))
            score = sum(min(pairs[pair], needed) for pair, needed in remaining.items())
            if score > best_score:
                best_orders, best_score = [], score
            if score == best_score:
                best_orders.append(order.copy())
        order = rng.choice(best_orders)
    else:
        rng.shuffle(order)

    selected = {
        label: iter(rng.sample(pools[label], count))
        for label, count in CLIPS_PER_LABEL.items()
    }
    return [next(selected[label]).copy() for label in order]


def plan_probes(stimulus):
    # we do not have probes for free-swipe
    if stimulus["interaction_mode"] != "fixed_probe":
        return []

    rng = Random()
    ranges = sorted(
        stimulus["probe_candidates"],
        key=lambda item: item["start_s"],
    )

    if stimulus["payoff_label"] == "terminal_primary":
        development = [item for item in ranges if item["category"] == "development"]
        buildup = [item for item in ranges if item["category"] == "buildup"]
        windows = []

        if development:
            early = development[0]
            start, end = early["start_s"], early["end_s"]
            windows.append((start, start + (end - start) / 3, early["category"]))

        late_ranges = buildup or development
        if late_ranges:
            late = late_ranges[-1]
            start, end = late["start_s"], late["end_s"]
            windows.append((end - (end - start) / 3, end, late["category"]))
    else:
        loops = [item for item in ranges if item["category"] == "loop"]
        if not loops:
            loops = [item for item in ranges if item["category"] == "loop_block"]

        if len(loops) > 3:
            first_cut = (len(loops) + 1) // 3
            second_cut = (2 * len(loops) + 1) // 3
            loops = [
                rng.choice(loops[:first_cut]),
                rng.choice(loops[first_cut:second_cut]),
                rng.choice(loops[second_cut:]),
            ]

        windows = [
            (item["start_s"], item["end_s"], item["category"])
            for item in loops
        ]

    probes = [
        {"time": rng.uniform(start, end), "category": category}
        for start, end, category in windows
    ]
    return sorted(probes, key=lambda probe: probe["time"])
