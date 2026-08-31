"""The local dashboard: a read-only window onto verdicts already on disk.

Nothing here classifies, ingests or writes. The pipeline stays a command-line
tool; this is the pane of glass over what it produced, which is what a
stakeholder asked for in the blueprint (Mode A, human-in-the-loop) and what a
reviewer needs before touching the CSV.
"""
