#
# The demo seed for Act 2 (#32): mock production data for the judge on a sample.
#
#   agent.json        a deliberately weak first version of Linden Grove's agent: the
#                     reference agent (eval/clinic-a/reference-agent.json) with the
#                     defects in weak.py planted, written by `python -m demo agent`
#   callers.json      the hidden callers the calls were made with (persona, goal,
#                     facts, style, and how speech-to-text garbled their words), and
#                     exact checks that help label what happened
#   labels.json       per call, the planted defects that showed and where, written
#                     after reading every transcript
#   workspace/        the workspace the demo installs as workspaces/linden-grove/:
#                     the requirements (clinic-a's spec, #29), version 1 (the weak
#                     agent), the calls as `production-mock` records and three client
#                     tickets
#
# callers.json and labels.json are the answer key: the judge (detect/judge.py) never
# reads them, as #58's detector never reads the synthetic labels. Only demo/evaluate.py
# does.
#
