# ORCA Learning Loop

The learning loop is how ORCA gets better over time.
Git is the nervous system — every learning is versioned, reviewed, and reversible.

## The Loop

```
ORCA acts on network
        ↓
Outcome observed (success / rollback / human override)
        ↓
Episode written → skills/past/episodes/
git commit + push → PR opened for review
        ↓
Engineer reviews: is this learning correct?
        ↓
Approved → merged → skills/past/ updated in repo
        ↓
Next ORCA startup: git pull → richer constraints loaded
        ↓
ORCA reasons better — acts again
        ↓
(repeat indefinitely)
```

---

## Git Operations Per Layer

| Layer | git pull | git push | Who approves PR |
|---|---|---|---|
| `skills/persistent/` | At startup | Human only — code review required | Senior engineer |
| `skills/past/` | Each analysis cycle | ORCA after every action | Any engineer |
| `skills/future/` | Nightly planning cycle | ORCA nightly | Automated CI only |
| `specs/` | At startup | Operator via PR | Engineer |
| `config_mgmt/candidate/` | Before pre-deploy | ORCA via open_pull_request | Engineer |
| `config_mgmt/running/` | Drift detection | Pipeline after NETCONF commit | Automated |

---

## Mistake Correction Cycle

```
ORCA makes mistake (wrong path / rollback / override)
        ↓
Episode written:
  outcome: failed
  learned_constraint: "avoid R5-R6 under peak load"
        ↓
git commit "learn: R5-R6 caused instability — add caution"
git push origin learn/episode-20260413-001
PR opened → engineer reviews
        ↓
Was it a one-off or a pattern?
  One-off → reject PR → no constraint added
  Pattern → approve PR → constraint merged
        ↓
git pull on next startup → ORCA avoids that path
```

---

## What Can and Cannot Be Learned

| Can be learned (past layer) | Cannot be learned (persistent layer) |
|---|---|
| Path preferences for this topology | Mission 1 threshold (90%) |
| Link caution levels from flap history | Safety rules (never push without diff) |
| Operator override patterns | Scope whitelist (allowed operations) |
| Time-of-day traffic patterns | Algorithm selection (CSPF always) |
| Vendor-specific quirks | Rollback trigger conditions |

Persistent layer changes require a human PR with code review.
They are never auto-proposed by ORCA.

---

## Compounding Value

```
Week 1:   ORCA follows persistent rules only
Week 4:   50 episodes — path preferences established
Week 12:  200 episodes — predicts failures before they happen
Week 26:  ORCA proposes persistent rule updates based on patterns
Year 2:   ORCA knows this network better than any individual engineer
```

The skills/past/ directory is ORCA's institutional memory.
It outlasts any individual engineer and compounds with every incident.
