# Warehouse processed JSON schema v2.0

Top-level keys: `schema_version` (`"2.0"`, optional on disk — missing implies v1.0), `game`, `plays`, `features`.

## New optional `Play` fields (nflverse PBP)

| Field | Type | nflverse column |
|-------|------|-----------------|
| `epa` | `float \| null` | `epa` |
| `wpa` | `float \| null` | `wpa` |
| `success` | `bool \| null` | `success` |
| `shotgun` | `bool \| null` | `shotgun` |
| `no_huddle` | `bool \| null` | `no_huddle` |
| `qb_dropback` | `bool \| null` | `qb_dropback` |
| `defenders_in_box` | `int \| null` | `defenders_in_box` |
| `offense_personnel` | `string \| null` | `offense_personnel` |
| `air_yards` | `float \| null` | `air_yards` |
| `yards_after_catch` | `float \| null` | `yards_after_catch` |
| `xpass` | `float \| null` | `xpass` |
| `passer_player_name` | `string \| null` | `passer_player_name` |
| `receiver_player_name` | `string \| null` | `receiver_player_name` |
| `rusher_player_name` | `string \| null` | `rusher_player_name` |
| `pass_length` | `string \| null` | `pass_length` |
| `pass_location` | `string \| null` | `pass_location` |
| `run_location` | `string \| null` | `run_location` |
| `run_gap` | `string \| null` | `run_gap` |

Absent keys or null values deserialize as Python `None`. `DerivedPlayFeatures` is unchanged in v2.0.
