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
