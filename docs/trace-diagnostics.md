# Comparing recorded runs

I built a tool to compare a local run that worked with one that failed. A failure could produce thousands of later differences. I wanted to find the first one worth investigating and keep the surrounding evidence.

The tool puts events from different sources on one timeline. It normalizes details such as process-specific addresses for comparison and keeps the recorded event and its source available in the report. A coarse fingerprint helps find similar runs. A sequence comparison aligns those runs and flags changes such as a configuration read succeeding in one run and failing in the other. The report distinguishes observed events from inferred links between them.

I also added a streaming reducer for repeated events. In one synthetic check it reduced 50,007 events to fewer than 200 while retaining the failure and the surrounding evidence. Another check aligned two 8,000-event timelines and found the one injected result change. Those are regression checks for the analysis code.

## Try a synthetic comparison

Set `PYTHONPATH` to `src` using the command in the README. Then run this in Python.

```python
from mho.blackbox.diff import DiffEngine
from mho.blackbox.events import BlackboxEvent, EventType
from mho.blackbox.timeline import Timeline

working = Timeline(label="working")
working.add(BlackboxEvent(type=EventType.FILE_OPEN, object="sample.cfg", result="SUCCESS"))

failed = Timeline(label="failed")
failed.add(BlackboxEvent(type=EventType.FILE_OPEN, object="sample.cfg", result="NAME NOT FOUND"))

finding = DiffEngine(working, failed).first_divergence()
print(finding.description())
```

The offline readers also accept existing ProcMon exports and ETW XML exports.
