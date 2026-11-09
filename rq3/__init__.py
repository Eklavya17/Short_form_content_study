"""RQ3: does showing same-topic videos back to back build momentum or tire viewers out?

Each participant scrolls three feeds that differ only in how they pick the next
video's topic:

    A  random topic, avoiding recently played ones (cooldown)
    B  engagement and likes make staying on the topic MORE likely
    C  engagement and likes make staying on the topic LESS likely

Module map (see docs/RQ3.md for the full plan):

    config         every tunable number, in one place
    catalog        clip metadata: topic, structure, stage and loop times
    build_catalog  turns the annotated CSV into the catalog JSON
    media          reads an MP4's duration and faststart flag from its header
    scoring        how well one video went (the engagement score e)
    feeds          the feed engine: picks the next video for A, B and C
    simulation     simulated viewers, used to tune config before any participant
    storage        database schema and queries for the study
    web            Flask routes for the study flow and the player API
    analysis       per-impression measures and the reported comparisons

The engine modules (config, catalog, scoring, feeds, simulation) import no Flask
or database code, so the simulator and the server run exactly the same logic.
"""
