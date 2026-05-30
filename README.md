# startrek

Offline CLI for Star Trek episode, Short Treks, and movie **original US air/release dates**.

Every query is a **calendar date range** (matching month/day, ignoring year). Results are always shown as a table.

## Install

Requires [Docker](https://docs.docker.com/get-docker/) and `git`.

```bash
curl -fsSL https://raw.githubusercontent.com/joachimvandekerckhove/startrek/v1.1.0/install.sh | bash
```

Ensure `~/bin` is on your PATH, then:

```bash
startrek today
startrek +1week
startrek lookup TNG 3 15
```

To update after a new release, re-run the install command.

## Usage

```bash
startrek                         # today
startrek 2019-12-12              # that calendar day
startrek 2026-06-01 2026-06-07   # explicit range
startrek +1week                    # today through one week from today
startrek -1week                    # one week ago through today
startrek +2days                    # today through two days from today
startrek +10days -5days            # today-5d through today+10d (either order)
startrek -s +1week                 # include plot summaries below the table
startrek lookup TNG 3 15           # episode lookup (table + summary)
startrek lookup ST 2 4             # Short Treks
startrek lookup film 3             # movie by release order
```

If nothing matches, you get a short message such as `No episodes on Sat May 30, 2026.` or `No episodes from ... to ...`.

`+0week` / `+0days` produce no output.

Series aliases for lookup: `TOS`, `TNG`, `DS9`, `VOY`, `ENT`, `TAS`, `DIS`, `PIC`, `LD`, `SNW`, `PRO`, `SA`, `ST` (Short Treks).

## Local development

Clone the repo and build the image (fast — no network fetch, DB is bundled):

```bash
git clone https://github.com/joachimvandekerckhove/startrek.git
cd startrek
docker build -t startrek:1.1.0 .
chmod +x host/startrek
./host/startrek today
```

Or run without Docker:

```bash
python3 scripts/build_db.py -o startrek.db   # maintainer only (~25 min)
STARTREK_DB=./data/startrek.db ./startrek today
```

## Publish a release (maintainers)

When episode data changes:

```bash
python3 scripts/build_db.py -o data/startrek.db
# bump VERSION in startrek
git add -A && git commit -m "Release 1.2.0"
git tag v1.2.0 && git push origin main --tags
```

Users then re-run the install one-liner (or set `STARTREK_VERSION=v1.2.0`).

## Data sources

The bundled database in `data/startrek.db` was built from:

- [STAPI](https://stapi.co/) — episode/movie metadata (Memory Alpha-derived)
- [Memory Alpha](https://memory-alpha.fandom.com/) — Short Treks episode list and plot teasers

Runtime is fully offline (`docker run --network none` works).

See [DATA.md](DATA.md) for licensing details.

## License

MIT for CLI code — see [LICENSE](LICENSE). Database content follows Memory Alpha CC BY-NC 3.0 terms.
