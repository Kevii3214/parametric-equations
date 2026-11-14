# Demo graph: 1415 Louisiana (id 233928)

`graph.json` is built by `backend/notebooks/make_demo_graph.py`. It is a **draft that must be checked by hand**
before the demo. No scan covers the street, the ground-floor lobby, an elevator bank or a floor corridor.

| Part | Source | Trust |
| --- | --- | --- |
| Regus Suite 1800 on floor 18 (`door18`, `rec_a`, `rec_b`, `phone_door`) | Matterport model `LJn59uoV759` (a Regus reception, hallway and phone room) | Door positions are measured. Which door is the suite entrance is a guess: the west door nearest the scan origin. |
| Floor 18 corridor and elevator bank (`hall18`, `el18`, `stair18`) | Estimated | Invented positions. Replace after walking or viewing the floor. |
| Ground floor (`st_main`, `lob1`, `el1`, `stair1`, `gar1`) | Estimated | Invented positions. Entrance placement should come from the Vexcel imagery. |
| Elevator and stair times | Assumed | 60 s up and 55 s down by elevator (wait plus ride); about 25 s per floor by stairs with a stretcher. |
| Elevator counts | CoStar | 15 passenger, 1 freight. Which elevators serve floor 18 is unknown. |

Other things to know:
- Suite 1800 is Regus according to CoStar's tenant list; floor 18 comes from the suite number, because CoStar's floor names are unreliable.
- RFID tag ids (`TAG-ENTRANCE-01`, `TAG-SUITE-1800`) are placeholders. Match them to the tags the hardware team has.
- Scan coordinates are relative to that scan's own centre, so the corridor outside the suite is not aligned to anything measured.
- There is deliberately no AED node: nothing in the data shows where one is.
