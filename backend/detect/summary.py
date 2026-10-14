#
# Call summaries: what detection reads (#57, #58). A live call record (#28), a
# simulated call (#26) and a synthetic call all reduce to the same summary, so the
# detector reads every source the same way. One JSON object per line:
#
#   id        unique call id
#   source    "synthetic", "simulated" or "live"
#   clinic    clinic id
#   version   agent version (a whole number; higher is newer)
#   start     ISO time the call started, clinic time, to the second
#   end       ISO time the call ended
#   caller    the caller's phone number
#   path      the nodes visited in order, one [node, turns, via] per visit: `turns`
#             is the number of agent turns in that visit and `via` the edge function
#             that entered it (absent for the first node)
#   tools     one [node, tool, ok] per catalog tool call, in order
#   ended     "completed" (an end node), "hang_up", "transfer" or "error"; the last
#             node in `path` is where the call ended
#
# Clinic records (bookings, changes, patients) are separate: they come from the
# clinic's system, not from the call. See synth.py for their format.
#

ENDINGS = ("completed", "hang_up", "transfer", "error")

# How a runner record's end_reason (sim/testfile.py) reads as a summary's ending.
# max_turns is a caller who never got what they called for, so a hang-up.
SIM_ENDINGS = {
    "end_node": "completed",
    "transfer": "transfer",
    "caller_hung_up": "hang_up",
    "max_turns": "hang_up",
    "agent_loop": "error",
}

TRANSFER_NODE = "transfer_to_human"  # the builder's one-off node, not part of the graph


def from_sim_record(record: dict, *, id: str, clinic: str, version: int, start: str, end: str, caller: str,
                    source: str = "simulated") -> dict:
    """The summary of a text runner record (sim/conversation.py). The record has no
    clock or caller number, so they are given."""
    path = [[record["start_node"], 0]]
    tools = []
    for turn in record["turns"]:
        if turn.get("speaker") != "agent" or turn.get("node") == TRANSFER_NODE or "calls" not in turn:
            continue
        path[-1][1] += 1
        entered = None
        for call in turn["calls"]:
            if call.get("kind") == "tool":
                result = call.get("result")
                tools.append([path[-1][0], call["name"], not (isinstance(result, dict) and "error" in result)])
            elif call.get("kind") == "edge" and call.get("to"):
                entered = [call["to"], 0, call["name"]]  # the last transition wins, as in Flows
        if entered:
            path.append(entered)
    return {
        "id": id,
        "source": source,
        "clinic": clinic,
        "version": version,
        "start": start,
        "end": end,
        "caller": caller,
        "path": path,
        "tools": tools,
        "ended": SIM_ENDINGS.get(record.get("end_reason"), "error"),
    }
