# KiCad schematic file format — what is actually in there

> Research behind rpcb's design. Figures come from one representative
> two-sheet sensor board (66 components, 75 nets, 212 pin connections).

Source files analysed:

| File | Role | Lines | Bytes |
|---|---|---|---|
| `board.kicad_sch` | Root sheet (page 1, A3) | 16,031 | 282,083 |
| `subsheet.kicad_sch` | Child sheet (page 2, A4) | 6,810 | 113,467 |
| **Total** | | **22,841** | **395,546** |

Format: KiCad 10.0 S-expression, file format version `20260306`.
**184 unique node paths, ~72 distinct node types.**

---

## 1. Headline numbers (why the current approach is inefficient)

| Metric | Value |
|---|---|
| Total bytes | 395,546 (~100k tokens) |
| Bytes that are **pure rendering/styling** | 228,466 — **57.8%** |
| Bytes in `lib_symbols` (symbol artwork library) | 120,018 — **30.3%** |
| Bytes in `(effects …)` font blocks alone | 85,196 — **21.5%** |
| Bytes in `(alternate …)` unused pin functions | 18,899 — **4.8%** |
| **Actual electrical content** | **119 symbols, 293 pins, 169 wires, 74 global labels, 30 junctions** |

The electrical graph is roughly **500 facts**. It is currently spread across ~100k tokens,
of which >90% is font size, stroke width, fill type, autoplace flags and UUIDs.

---

## 2. Top-level node types

| Node | Count | Bytes | % file | Electrically meaningful? |
|---|---|---|---|---|
| `symbol` | 119 | 212,043 | 53.6% | **Yes** — placed component instances |
| `lib_symbols` | 2 | 120,018 | 30.3% | **Partly** — only pin name/number/type matter |
| `global_label` | 74 | 31,015 | 7.8% | **Yes** — the only cross-sheet net connector |
| `wire` | 169 | 25,583 | 6.5% | **Yes** — but only the 2 endpoints |
| `junction` | 30 | 3,397 | 0.9% | **Yes** — resolves crossing-vs-connected |
| `text` | 4 | 1,088 | 0.3% | Design-intent notes (useful for review) |
| `sheet` | 1 | 772 | 0.2% | **Yes** — hierarchy link |
| `polyline` | 3 | 462 | 0.1% | No — cosmetic divider lines |
| `sheet_instances` | 1 | 49 | — | No — page numbering |
| `version`/`generator`/`generator_version` | 2 each | 132 | — | No |
| `uuid` (sheet-level) | 2 | 90 | — | No |
| `paper` | 2 | 24 | — | No |
| `embedded_fonts` | 1 | 19 | — | No |

---

## 3. File header

| Field | Arity | Sample | Keep? | Description |
|---|---|---|---|---|
| `version` | 1 | `20260306` | ✗ | File format date-version |
| `generator` | 1 | `eeschema` | ✗ | Producing tool |
| `generator_version` | 1 | `10.0` | ✗ | KiCad version |
| `uuid` | 1 | `745e1ba3-…` | ⚠ | Sheet identity — needed to resolve `instances` paths |
| `paper` | 1 | `A3`, `A4` | ✗ | Page size |
| `embedded_fonts` | 1 | `no` | ✗ | Font embedding flag |

---

## 4. `lib_symbols` — the symbol definition library

Defines the 25 distinct part types used. **30.3% of the file; only the `pin` rows carry signal.**

| Field | Count | Arity | Sample | Keep? | Description |
|---|---|---|---|---|---|
| `symbol` (lib) | 25 | 1 | `Transceiver:XCVR_A` | **✓** | Library symbol ID — joins to instance `lib_id` |
| `power` | 5 | 1 | `global` | **✓** | **Marks symbol as a power symbol → implicit global net** |
| `pin_names` / `offset` | 21 | 1 | `0.254` | ✗ | Name label offset |
| `pin_names` / `hide` | 15 | 1 | `yes` | ✗ | Hide pin names |
| `pin_numbers` / `hide` | 14 | 1 | `yes` | ✗ | Hide pin numbers |
| `in_bom` | 25 | 1 | `yes`/`no` | ⚠ | BOM inclusion default |
| `on_board`, `in_pos_files`, `exclude_from_sim`, `embedded_fonts`, `duplicate_pin_numbers_are_jumpers` | 25 each | 1 | `yes`/`no` | ✗ | Behaviour flags |
| `property` | 176 | 2–3 | `Reference U`, `Value XCVR-A-01` | ⚠ | Library defaults — overridden per instance |

### 4.1 `lib_symbols/symbol/symbol` — graphical body units (45)

| Field | Count | Arity | Sample | Keep? | Description |
|---|---|---|---|---|---|
| `symbol` (unit) | 45 | 1 | `XCVR_A_0_1` | ⚠ | Unit/body-style sub-block. Suffix `_U_B` = unit, body style |
| `polyline` + `pts`/`xy` | 71 / 195 | 2 | `5.08 5.08` | ✗ | **Body outline artwork — pure noise** |
| `rectangle` (`start`,`end`) | 10 | 2 | `0.8636 0.127` | ✗ | Body box artwork |
| `circle` (`center`,`radius`) | 1 | 1–2 | `0 0`, `1.27` | ✗ | Artwork |
| `arc` (`start`,`mid`,`end`) | 1 | 2 | `-1.524 -0.762` | ✗ | Artwork |
| `fill` / `type` | 83 | 1 | `none`,`outline`,`background` | ✗ | Fill style |
| `stroke` / `width`, `type` | 83 | 1 | `0.127`, `default` | ✗ | Line style |

### 4.2 `lib_symbols/…/pin` — **the critical table** (168 pin definitions)

| Field | Count | Arity | Sample | Keep? | Description |
|---|---|---|---|---|---|
| `pin` | 168 | 2 | `input line`, `power_in line`, `bidirectional line`, `output line` | **✓✓** | **Arg 1 = electrical type** (drives ERC), arg 2 = graphic style |
| `pin/number` | 168 | 1 | `1`, `2`, `3` | **✓✓** | **Pin number — joins to instance `pin`** |
| `pin/name` | 168 | 1 | `TXD`, `VSS`, `VDD`, `RXD` | **✓✓** | **Human-readable function name** |
| `pin/at` | 168 | 3 | `-2.54 -2.54 0` | **✓✓** | x, y, angle **relative to symbol origin**. **VERIFIED: this IS the electrical connection point** — the wire attaches here |
| `pin/length` | 168 | 1 | `7.62` | ✗ | Pin stub length, drawn from `at` *inward* toward the body. **Not needed for connectivity** (empirically confirmed: using `at` alone scored 60.3% wire-coincidence vs 17.7% for `at ± length·dir`) |
| `pin/hide` | 6 | 1 | `yes` | ⚠ | Hidden pins (often power) — still electrically live |
| `pin/alternate` | **441** | 3 | `RTC_OUT1 bidirectional line` | ✗ | **Alternate pin functions (MCU AF list). 18.9 kB of noise — only matters if an alt function is actually selected** |
| `pin/name/effects/font/size` | 168 | 2 | `1.27 1.27` | ✗ | Text size |
| `pin/number/effects/font/size` | 168 | 2 | `1.27 1.27` | ✗ | Text size |

---

## 5. `symbol` — placed component instances (119)

| Field | Count | Arity | Sample | Keep? | Description |
|---|---|---|---|---|---|
| `lib_id` | 119 | 1 | `power:GND`, `Device:R_US` | **✓✓** | **Joins instance → `lib_symbols` definition** |
| `lib_name` | 1 | 1 | `SENSOR_B_1` | ⚠ | Override when instance uses a modified local copy |
| `at` | 119 | 3 | `48.26 173.99 0` | **✓** | **x, y, rotation (0/90/180/270) — origin for pin transform** |
| `mirror` | 6 | 1 | `y` | **✓** | **Mirror axis — flips pin coordinates. Easy to get wrong** |
| `unit` | 119 | 1 | `1`, `2` | **✓** | Which unit of a multi-unit part |
| `body_style` | 119 | 1 | `1` | ⚠ | DeMorgan variant |
| `uuid` | 119 | 1 | `00bcd267-…` | ⚠ | Instance identity — needed for `instances` path join |
| `pin` | 293 | 1 | `1`, `2` | **✓** | Pin number + its own UUID (net-tie identity) |
| `pin/uuid` | 293 | 1 | `d77eb574-…` | ✗ | Per-pin UUID |
| `property` | 819 | 2–3 | see §5.1 | **✓** | Instance metadata |
| `instances/project` | 119 | 1 | `board` | ✗ | Project name |
| `instances/project/path` | 119 | 1 | `/745e1ba3…/0e7a7907…` | **✓** | **Hierarchical sheet path — disambiguates repeated sheets** |
| `instances/…/reference` | 119 | 1 | `R8`, `D9`, `#PWR025` | **✓✓** | **Actual refdes.** `#PWR*` = power symbol |
| `instances/…/unit` | 119 | 1 | `1`, `2` | **✓** | Unit for this instance path |
| `in_bom` | 119 | 1 | `yes`/`no` | **✓** | BOM inclusion |
| `dnp` | 119 | 1 | `no` | **✓✓** | **Do Not Populate — critical for design review** |
| `exclude_from_sim`, `on_board`, `in_pos_files`, `fields_autoplaced` | 119/96 | 1 | `no`/`yes` | ✗ | Flags |

### 5.1 `symbol/property` — 819 instances, 17 distinct names

| Property name | Count | Keep? | Description |
|---|---|---|---|
| `Reference` | 144 | **✓✓** | Refdes (`R8`, `U3`, `#PWR04`) |
| `Value` | 144 | **✓✓** | Value / part name (`10k`, `GND`, `XCVR-A-01`) |
| `Footprint` | 144 | **✓** | Land pattern |
| `Datasheet` | 144 | ⚠ | Datasheet link |
| `Description` | 144 | ⚠ | Long text; for power symbols encodes the net name |
| `MPN` | 48 | **✓** | Manufacturer part number |
| `manufacturer` | 36 | **✓** | Manufacturer |
| `Intersheetrefs` | 74 | ✗ | `${INTERSHEET_REFS}` — auto-generated cross-ref text |
| `KLC_S4.1`, `KLC_S3.3` | 66 each | ✗ | KiCad Library Convention audit tags |
| `ki_keywords` | 24 | ✗ | Search keywords |
| `ki_fp_filters` | 19 | ✗ | Footprint filters |
| `ki_locked` | 5 | ✗ | Lock flag |
| `link` | 4 | ✗ | URL |
| `Sim.Pins` | 3 | ✗ | Simulation pin mapping |
| `Sheetname` / `Sheetfile` | 1 each | **✓** | On the `sheet` node — hierarchy |

Every one of these 819 properties carries an `at`, `hide`, `show_name`, `do_not_autoplace`
and a nested `effects/font/size` block. **That wrapper is ~90% of the property bytes.**

---

## 6. Connectivity nodes

### 6.1 `wire` (169)

| Field | Count | Arity | Sample | Keep? | Description |
|---|---|---|---|---|---|
| `pts/xy` | 338 | 2 | `203.2 148.59` | **✓✓** | **Exactly 2 endpoints per wire — the entire graph edge** |
| `stroke/width` | 169 | 1 | `0` | ✗ | Line width |
| `stroke/type` | 169 | 1 | `default` | ✗ | Line style |
| `uuid` | 169 | 1 | `01ef5c91-…` | ✗ | Wire identity |

### 6.2 `junction` (30)

| Field | Count | Arity | Sample | Keep? | Description |
|---|---|---|---|---|---|
| `at` | 30 | 2 | `68.58 134.62` | **✓✓** | **Explicit connection dot — wires crossing WITHOUT one are NOT connected** |
| `diameter` | 30 | 1 | `0` | ✗ | Dot size |
| `color` | 30 | 4 | `0 0 0 0` | ✗ | Dot colour |
| `uuid` | 30 | 1 | — | ✗ | Identity |

### 6.3 `global_label` (74)

| Field | Count | Arity | Sample | Keep? | Description |
|---|---|---|---|---|---|
| *(value)* | 74 | 1 | `SPI_NCS`, `VBUS_5V`, `I2C_SCL`, `BUS_L` | **✓✓** | **Net name. Same name anywhere in the project = same net** |
| `at` | 74 | 3 | `299.72 161.29 0` | **✓✓** | Attachment point — must match a wire endpoint |
| `shape` | 74 | 1 | `input` | ⚠ | Port direction hint (cosmetic in KiCad, but useful for review) |
| `fields_autoplaced` | 74 | 1 | `yes` | ✗ | Autoplace flag |
| `property Intersheetrefs` | 74 | 2 | `${INTERSHEET_REFS}` | ✗ | Auto cross-reference text + full effects block |
| `effects/font/size`, `justify` | 74 each | 1–2 | `1.27 1.27`, `left` | ✗ | Text styling |
| `uuid` | 74 | 1 | — | ✗ | Identity |

### 6.4 `sheet` (1) — hierarchy

| Field | Arity | Sample | Keep? | Description |
|---|---|---|---|---|
| `property Sheetname` | 2 | `sensors` | **✓** | Sheet instance name |
| `property Sheetfile` | 2 | `subsheet.kicad_sch` | **✓** | Child file |
| `uuid` | 1 | `0e7a7907-…` | **✓** | Path component for child `instances` |
| `at`, `size` | 2 | `25.4 71.12`, `48.26 38.1` | ✗ | Box geometry |
| `stroke`, `fill`, `dnp`, `in_bom`, `on_board`, `exclude_from_sim`, `fields_autoplaced` | 1 | — | ✗ | Style/flags |
| `instances/project/path/page` | 1 | `2` | ✗ | Page number |

> **No `sheet_pin` nodes exist.** See §8.

### 6.5 `text` (4) — free annotations

| Field | Count | Sample | Keep? | Description |
|---|---|---|---|---|
| *(value)* | 4 | `"CAN transceiver already protects the CANL and CANH lines IEC61000-4-2 up to ±14 kV"` | **✓** | **Designer intent — genuinely valuable for design review** |
| `at`, `effects`, `exclude_from_sim`, `uuid` | 4 | — | ✗ | Placement/style |

### 6.6 `polyline` (3) — sheet-level cosmetic lines

Pure decoration (section dividers). `pts/xy` ×6, `stroke`, `uuid`. **Not electrical** — do not confuse with `wire`.

---

## 7. Node types that are ABSENT (verified zero occurrences)

This shapes the extraction design significantly:

| Node type | Count | Consequence |
|---|---|---|
| `no_connect` | **0** | No pin is explicitly marked unconnected — every floating pin is ambiguous (intentional or a bug) |
| `label` (local) | **0** | No local net names |
| `hierarchical_label` | **0** | No sheet-boundary ports |
| `sheet_pin` | **0** | **The `sensors` sub-sheet has no pins at all** |
| `bus`, `bus_entry` | **0** | No bus abstraction — all nets are individual |
| `netclass_flag` | **0** | No per-net class assignment in schematic |
| `image`, `table`, `rule_area` | **0** | — |

---

## 8. The key architectural finding

**Connectivity in this project is 100% geometric + global-label based.**

Because there are no `sheet_pin`, no `hierarchical_label`, and no local `label` nodes,
the netlist can only be recovered by:

1. **Computing absolute pin positions** — take each instance's `at (x y rot)` and `mirror`,
   then transform each `lib_symbols` pin's `at` into sheet coordinates:
   ```
   (x, y) = (pin.x, -pin.y)                  # lib is Y-up, sheet is Y-DOWN
   (x, y) = rotate_CLOCKWISE(x, y, sym.rot)  # NOT counter-clockwise
   if mirror == 'y': x = -x
   abs = (sym.x + x, sym.y + y)
   ```
   *(This is the step most likely to be done wrong — see §10.)*
2. **Chaining wires** by exact shared endpoint coordinates into connected components.
3. **Applying junctions** — a wire endpoint touching another wire's *midpoint* only connects
   if a `junction` exists at that coordinate.
4. **Merging by name** — all components touching a `global_label` of the same name merge into
   one net, project-wide across both sheets.
5. **Merging power symbols** — the 5 `(power global)` lib symbols (`GND`, `+3.3V`, `+5V`, …)
   act as implicit global labels; their `Value` is the net name and their `#PWR*` refdes is
   not a real component.

**An LLM reading the raw file cannot do steps 1–3 reliably** — it would have to do
floating-point coordinate arithmetic across 293 pins and 338 wire endpoints. This is the
root cause of the unreliability, not merely the file size.

The fix is therefore **not** "strip the styling" — it is "resolve the geometry once,
deterministically, and hand the LLM a named net list." Stripping alone would still leave
the model doing coordinate matching.

---

## 9. Proposed keep-set (for the next step)

Everything marked **✓✓** or **✓** above collapses to roughly:

```
components:  ref, lib_id, value, footprint, mpn, dnp, sheet, unit
pins:        ref.pin_number, pin_name, electrical_type
nets:        net_name → [ref.pin, …]  (already resolved)
notes:       the 4 free-text annotations
```

Estimated output size: **~500 facts, ~3–6k tokens** versus 100k today — a **~20× reduction**,
with the geometry pre-resolved so the model never does arithmetic.

---

## 10. Verified: the geometry rules (and the trap)

A full resolver was built and diffed against KiCad's own exporter
(`kicad-cli sch export netlist`). Result: **75/75 nets with identical pin membership.**

Rules confirmed empirically:

| # | Rule |
|---|---|
| 1 | A lib pin's `at` **is** the connection point. `length` is irrelevant to connectivity. |
| 2 | Library coords are **Y-up**; sheet coords are **Y-down**. Negate `y` before rotating. |
| 3 | Symbol `rot` rotates **clockwise** in sheet coordinates. |
| 4 | Two items at the *same coordinate* are connected: pin↔pin, pin↔wire-end, pin↔label. |
| 5 | A wire endpoint touching another wire's **interior** needs a `junction` to connect. A **pin** landing mid-wire connects with no junction. |
| 6 | A `global_label` name is **project-global** — merges components across both sheets. |
| 7 | A **power symbol's `Value`** is *also* a project-global net name (`(power global)` in its lib def). All `+3.3V` symbols are one net, everywhere. |
| 8 | When a net carries both a label and a power symbol, **the label name wins** as the display name (e.g. `+5V` symbol on a `VMAIN`-labelled net → KiCad calls it `VMAIN`). |
| 9 | `#PWR*` refdes are **not real components** — exclude them from net membership. |

### The trap that makes hand-rolled extraction dangerous

Scoring "how many pins land on a wire" **cannot** distinguish CW from CCW rotation:
all four rotation/mirror variants scored **identically (222/368 = 60.3%)**.

Yet CCW silently swapped pins 1↔2 on every 270°-rotated part. Concretely, `D4` at
`(48.26 35.56 270)`:

| | pin 1 "K" | pin 2 "A" |
|---|---|---|
| **Clockwise (correct)** | (48.26, **31.75**) → `UART_TX` | (48.26, **39.37**) → `GND` |
| Counter-clockwise (wrong) | (48.26, 39.37) → `GND` | (48.26, 31.75) → `UART_TX` |

Both versions have *every pin landing neatly on a wire*. The wrong one reverses the
polarity of 4 protection diodes — exactly the class of error a design review exists to
catch. **A netlist that is confidently wrong is worse than no netlist.**

→ Therefore: **do not reimplement the geometry. Use `kicad-cli sch export netlist`**
(present at `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`), which resolves
all of the above and additionally emits `pintype`, `pinfunction`, footprints and
`libparts`. The extractor's job is then *reformatting*, not geometry — a class of task
with no silent-failure mode.

---

## 11. Open design choices


- **Format**: flat net-list JSON vs. adjacency graph vs. compact DSL text
- **Net-centric vs. component-centric** ordering (or both, cross-linked)
- Whether to auto-flag review-relevant conditions (single-pin nets, floating pins,
  power pins with no supply, missing decoupling) as part of the extraction
- Whether to verify the extractor against KiCad's own netlist exporter for ground truth
