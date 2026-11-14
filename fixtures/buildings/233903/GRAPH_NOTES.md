# Williams Tower graph (id 233903)

`graph.json` is built by `backend/notebooks/make_williams_graph.py`. Unlike the first demo building, most of the
indoor part is **measured**. It is still a draft: check the estimated parts by hand before the demo.

| Part | Source | Trust |
| --- | --- | --- |
| Floor 56 suite (`door56`, passage nodes `p*`, patient rooms `room*`) | Matterport model `eJKnR3x44eh` ("56th Floor"): every doorway and open gap in its vector data | Door and gap positions are measured. Rooms are joined only where a straight walk stays inside the room outline. |
| Suite identity | CoStar tenant list: Suite 5600, Titan Global Advisory | The scan shows a staffed reception with glass offices; the name "56th Floor" is the scan's, so this match is by floor. |
| The suite entrance (`door56`) | The 2 m glass doorway at the scan origin | A guess that it is the entrance from the elevator corridor. Verify in the scan. |
| Elevator corridor, elevators, stairs on floor 56 (`hall56`, `el56`, `stair56`) | Estimated | Invented positions north of the suite door. |
| Ground floor (`st_main`, `lob1`, `el1`, `stair1`, `gar1`) | Estimated | Invented positions. Entrance placement should come from the Vexcel imagery. |
| Elevator and stair times | Assumed | 60 s up and 55 s down by elevator (wait plus ride); about 25 s per floor by stairs with a stretcher (55 floors is a very long climb). |
| Elevator count | CoStar | 39 passenger elevators; which serve floor 56 is unknown. |

Other things to know:
- Patient locations you can route to: the conference room, kitchen, coworking space and the office at the north end of the east wing. Other rooms have no labelled node.
- The coworking space and kitchen have no doors in the scan; they connect through open gaps, which the scan marks as invisible edges.
- One doorway belonged to a single room (a door to somewhere the scan does not cover) and was skipped.
- RFID tag ids (`TAG-ENTRANCE-01`, `TAG-SUITE-5600`) are placeholders. Match them to the tags the hardware team has.
- There is deliberately no AED node: nothing in the data shows where one is.
