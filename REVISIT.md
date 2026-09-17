# REVISIT

Things about this repository that are **deliberately not in the commit messages or the code**,
usually because the commit message is already written and rewriting it is worse than annotating it.

## Commits that carry a `git notes` correction

Some commits here have a correction attached with `git notes`. Notes are the right mechanism —
they do not rewrite history and they travel with the commit — but:
**`git log` does not show them unless you ask, and git does not fetch them by default.**

- The fetch refspec is configured in this repo, so `git fetch` / `git pull` brings notes along.
- To *read* them: `git log --notes`, or `git show <sha> --notes`.

### `500ae05`

Its message describes the Phase B `chile_scraper.py` changes, but
`git show 500ae05 -- juris-search/chile_scraper.py` is **empty** — the commit contains only `.dev`
docs plus unrelated `violation-refiner/build/CL-029/**` artifacts. The scraper changes actually
landed in `2f4a2cd`.

Read the full correction with:

```
git notes show 500ae05
```

Do not revert `500ae05`; it carries the `.dev` docs.

## The working tree is usually dirty, and not from you

`violation-refiner/**` is frequently modified in the working tree by another process — **11 files**
at the time of writing (`CL-029/*.json`, `MANIFEST.txt`, `Validation/*`, and six `violation_pack/*.py`).
This has now tripped two agents in two passes.

**Stage explicitly.** `git add -A`, `git commit -a` and `git add .` will sweep those files into
whatever you are committing, producing a commit whose contents do not match its message — the exact
defect documented above for `500ae05`, reached from a third direction. Use:

```
git add <the files you actually changed>
git diff --cached --name-only    # verify the staged set before committing
```

## Grepping this repo by filename is a false-positive machine

`chile_scraper`, for example, matches `chile_scraper.py` **and** `03-chile_scraper-playbook.md`
(plus `update-juris_indexer.md`-style docs). A verification command like

```
git show --name-only --format= HEAD | grep -c chile_scraper    # returns 1, looks like a hit
```

reports a finding that is not one. Anchor the pattern (`grep 'chile_scraper\.py$'`) or resolve the
path exactly (`git rev-parse HEAD:juris-search/chile_scraper.py`).
