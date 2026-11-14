# Rabinowitz Hall (JRR) graph (id `jrr`)

This building is **not in the CoStar kit**. Its snapshot was made from the Matterport scan `P3S6VUTP3qB`
("Princeton - Rabinowitz Hall"), Vexcel imagery, and a record written by hand (`record.json`).
`graph.json` is built by `backend/notebooks/make_jrr_graph.py` from the scan's data. It is a draft: check the
inferred parts by hand.

| Part | Source | Trust |
| --- | --- | --- |
| Walkable waypoints (`s*`, 65 of them) | The scan's camera positions on each level | Measured: the camera stood on walkable floor. |
| Which waypoints are joined | Straight line stays inside the walkable room outlines (atrium voids cut out) and crosses no wall except at a measured doorway | Good in open halls; can be wrong in tight spaces. |
| Levels | The scan calls them Floor 2 (the open atrium hall, 0 m) and Floor 3 (a ring corridor with a classroom, 4 m up) | The names are the scan's. Whether they are the building's real second and third floors is not known. "Floor 1" in the scan is empty. |
| **Glass entrance** (`entrance1`) | **Placed from a description.** The scan marks no exterior doorway, so it is placed from the scan's opening view (the camera pose Matterport stores for the thumbnail: at the origin, facing compass bearing 55.5 degrees) and what someone who knows the building sees in it: the arched glass doors behind the orange tables | Good to a few metres: it lands on the east wall of the atrium hall near (15.2, 4.4), where scan positions also sit. |
| **Stairs** (`s57` lower to `s58` upper) | **Placed from a description.** The glass staircase is to the left of the start, so about 7 m out at bearing 20 degrees, against the north wall. The scan positions on the two levels there are stacked almost on top of each other | Position good to a few metres. The climb time (30 s up, 25 s down with a stretcher) is an assumption. |
| Patient locations | The classroom, the two stair landings (north and south), the east side of the upper corridor, and the atrium hall | Chosen by room type in the scan; the nearest camera position is used. |

Other things to know:
- **No elevator.** The scan shows none, so none is invented. With the stairs closed, the upper level cannot be reached.
- The outer doors of the upper corridor and the windows on the lower level lead to spaces the scan did not capture, so they are not used as entrances.
- A single scan position was taken between the two levels at (1.4, -9.1), 2 m up. It suggests a second staircase on the south side, which is not modelled.
- The building has no street address in the data: Matterport only gives "Princeton, NJ 08544". The record uses "Princeton University".
- RFID tag ids (`TAG-ENTRANCE-01`, `TAG-CLASSROOM-01`) are placeholders. Match them to the tags the hardware team has.
- There is deliberately no AED node: nothing in the data shows where one is.
