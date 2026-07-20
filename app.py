import streamlit as st
import requests
import altair as alt
import pandas as pd
from datetime import datetime
from fpdf import FPDF

st.set_page_config(
    page_title="Fern ROI calculator",
    page_icon="assets/fern-favicon-32x32.png",
    layout="wide",
)

st.logo(
    "assets/fern-logo.svg",
    link="https://www.fernlabs.ai",
    size="large",
    icon_image="assets/fern-icon.svg",
)

# ---- Scenario configs -------------------------------------------------
# current_hours_per_charge is today's baseline (before Fern) — this is what differs by
# current tool. hours_with_fern_per_charge is always 2: Fern gets every charge to the same
# ~2 hr turnaround regardless of what you're using today.
HOURS_WITH_FERN = 2

SCENARIOS = {
    "no_tool": {
        "label": "A - Not using an AI tool for EEOC charges",
        "current_hours_per_charge": 20,
        "hours_with_fern_per_charge": HOURS_WITH_FERN,
        "outside_counsel_multiplier": 1.0,
        "note": "No existing AI tool for employment disputes — Fern delivers full value.",
    },
    "limited": {
        "label": "B - Limited AI tool use",
        "current_hours_per_charge": 15,
        "hours_with_fern_per_charge": HOURS_WITH_FERN,
        "outside_counsel_multiplier": 0.97,
        "note": "General-purpose or limited AI tools help a little with drafting and research, "
        "but aren't purpose-built for employment law charges — your team still does "
        "significant manual review, and reliance on outside counsel stays about the same.",
    },
    "high": {
        "label": "C - High AI tool use / custom legal tech product",
        "current_hours_per_charge": 5,
        "hours_with_fern_per_charge": HOURS_WITH_FERN,
        "outside_counsel_multiplier": 0.9,
        "note": "Sophisticated or custom-built tools already save meaningful time, but "
        "employment-law-specific grounding, citation-checked drafting, and workflow "
        "automation still add incremental value on top.",
    },
}

RAMP_PCT = [0.4, 0.7, 1.0]

# ---- Inhouse fully-loaded hourly rate: (annual salary x loaded-cost multiplier) / hrs per year
LOADED_COST_MULTIPLIER = 1.5
WORK_HOURS_PER_YEAR = 1920  # 40 hrs/week x 48 weeks/year

# ---- Brand chart colors (from fernlabs.ai's own palette) ----------------
FERN_FOREST = "#1a3d26"  # darkest — net value (the headline number)
FERN_GREEN = "#285638"  # primary — main value component
FERN_PALE = "#6da67a"  # lighter — secondary value component
FERN_AMBER = "#c97b2a"  # distinct hue — cost, never confused with value

# ---- Session state defaults --------------------------------------------
DEFAULTS = {
    "buyer_type": "In-house legal/HR team",
    "session_mode": "Self-serve preview",
    "scenario_label": next(iter(SCENARIOS.values()))["label"],
    "current_hours_per_charge": next(iter(SCENARIOS.values()))["current_hours_per_charge"],
    "use_ramp": False,
    "pricing_model": "Per charge",
    "industry": "Technology",
    "employee_count": "50",
    "charges_per_year": 120,
    "inhouse_pct_today": 75,
    "inhouse_pct_fern": 100,
    "outside_counsel_cost_per_charge": 15000,
    "annual_salary": 192_000,
    "hourly_labor_cost": 150,
    "fern_cost_per_charge": 900,
    "setup_comments": "",
    "fern_monthly_fixed": 3000,
    "lead_name": "",
    "lead_email": "",
    "lead_company": "",
}

for _key, _value in DEFAULTS.items():
    st.session_state.setdefault(_key, _value)


def inhouse_hourly_rate():
    return (st.session_state.annual_salary * LOADED_COST_MULTIPLIER) / WORK_HOURS_PER_YEAR


def reset_inputs():
    for key, value in DEFAULTS.items():
        st.session_state[key] = value


def sync_hours_to_scenario():
    """Re-fill the time-spent-per-charge field with a typical suggestion whenever the
    setup answer changes. The field stays fully editable afterward — this only sets
    the starting point."""
    for cfg in SCENARIOS.values():
        if cfg["label"] == st.session_state.scenario_label:
            st.session_state.current_hours_per_charge = cfg["current_hours_per_charge"]
            return


def format_currency(num):
    return f"${round(num):,}"


def breakdown_chart(rows, value_format="$,.0f", value_prefix="$", value_suffix=""):
    """Horizontal bar chart for a small set of named amounts.

    rows: list of (label, amount, color) tuples, in top-to-bottom display order.
    value_format: Vega-Lite axis number format (no currency/unit symbols).
    value_prefix / value_suffix: text wrapped around the formatted number in bar-end
    labels and the axis (e.g. prefix="$" for dollars, suffix=" hrs" for hours).
    """
    df = pd.DataFrame(rows, columns=["Category", "Amount", "Color"])
    order = df["Category"].tolist()
    colors = df["Color"].tolist()

    bars = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, height=26)
        .encode(
            x=alt.X("Amount:Q", title=None, axis=alt.Axis(format=value_format, grid=False)),
            y=alt.Y("Category:N", title=None, sort=order, axis=alt.Axis(labelLimit=160)),
            color=alt.Color("Category:N", scale=alt.Scale(domain=order, range=colors), legend=None),
            tooltip=[
                alt.Tooltip("Category:N", title="Category"),
                alt.Tooltip("Amount:Q", title="Amount", format=value_format),
            ],
        )
    )
    df["Label"] = df["Amount"].apply(lambda a: f"{value_prefix}{a:,.0f}{value_suffix}")
    labels = (
        alt.Chart(df)
        .mark_text(align="left", dx=6, color="#1a1a18")
        .encode(x=alt.X("Amount:Q"), y=alt.Y("Category:N", sort=order), text=alt.Text("Label:N"))
    )
    return (bars + labels).properties(height=len(df) * 42 + 20)


def calculate_roi(is_law_firm, scenario_cfg, pricing_model, use_ramp):
    charges_per_year = st.session_state.charges_per_year
    outside_counsel_cost_per_charge = st.session_state.outside_counsel_cost_per_charge
    fern_cost_per_charge = st.session_state.fern_cost_per_charge
    fern_monthly_fixed = st.session_state.fern_monthly_fixed
    inhouse_pct_today = st.session_state.inhouse_pct_today / 100
    inhouse_pct_fern = st.session_state.inhouse_pct_fern / 100

    # The user's own real-world estimate drives the math — the scenario's hours are only
    # a starting suggestion (auto-filled when they change their answer, but editable).
    current_hours_per_charge = st.session_state.current_hours_per_charge
    hours_with_fern_per_charge = min(scenario_cfg["hours_with_fern_per_charge"], current_hours_per_charge)
    effective_hours_saved_per_charge = current_hours_per_charge - hours_with_fern_per_charge
    effective_outside_counsel_per_charge = outside_counsel_cost_per_charge * scenario_cfg["outside_counsel_multiplier"]

    if is_law_firm:
        # A law firm IS outside counsel, so every matter is "in-house" to the firm —
        # there's no split, and hours freed are billable capacity unlocked, not cost avoided.
        # Billable rate is a direct client-billing rate, not derived from a salary.
        hourly_rate = st.session_state.hourly_labor_cost
        charges_inhouse_today = charges_per_year
        charges_outside_today = 0
        charges_inhouse_fern = charges_per_year
        charges_outside_fern = 0
    else:
        # In-house: because Fern makes in-house work faster, a customer may plan to bring
        # more charges in-house than they do today — so "today's split" and "the split once
        # they have Fern" are tracked as two separate, independently editable assumptions.
        hourly_rate = inhouse_hourly_rate()
        charges_inhouse_today = charges_per_year * inhouse_pct_today
        charges_outside_today = charges_per_year - charges_inhouse_today
        charges_inhouse_fern = charges_per_year * inhouse_pct_fern
        charges_outside_fern = charges_per_year - charges_inhouse_fern

    # Charges kept in-house get faster (time savings); charges that move from outside
    # counsel to in-house avoid that fee entirely (fees savings) — both compared at the
    # SAME charge volume, just re-split between today's mix and the with-Fern mix.
    inhouse_labor_cost_today = charges_inhouse_today * current_hours_per_charge * hourly_rate
    inhouse_labor_cost_with_fern = charges_inhouse_fern * hours_with_fern_per_charge * hourly_rate
    inhouse_time_savings = inhouse_labor_cost_today - inhouse_labor_cost_with_fern

    outside_cost_today = charges_outside_today * effective_outside_counsel_per_charge
    outside_cost_with_fern = charges_outside_fern * effective_outside_counsel_per_charge
    outside_fees_savings = outside_cost_today - outside_cost_with_fern

    hours_inhouse_today = charges_inhouse_today * current_hours_per_charge
    hours_inhouse_with_fern = charges_inhouse_fern * hours_with_fern_per_charge
    total_hours_saved = hours_inhouse_today - hours_inhouse_with_fern

    total_value_year1_full = inhouse_time_savings + outside_fees_savings

    # What handling this same caseload costs today (no Fern, today's in-house/outside mix)
    # vs. after adopting Fern (the with-Fern mix) — nets out to exactly
    # total_value_year1_full - fern_annual_cost.
    cost_without_fern = inhouse_labor_cost_today + outside_cost_today

    fern_annual_cost = (
        charges_per_year * fern_cost_per_charge
        if pricing_model == "Per charge"
        else (fern_monthly_fixed or 3000) * 12
    )
    cost_with_fern = inhouse_labor_cost_with_fern + outside_cost_with_fern + fern_annual_cost

    net_value_year1_full = total_value_year1_full - fern_annual_cost
    payback_months = fern_annual_cost / (total_value_year1_full / 12) if total_value_year1_full > 0 else 0
    money_multiple = total_value_year1_full / fern_annual_cost if fern_annual_cost > 0 else 0

    yearly_ramp = []
    for pct in RAMP_PCT:
        value = total_value_year1_full * pct
        cost = fern_annual_cost * pct if pricing_model == "Per charge" else fern_annual_cost
        yearly_ramp.append({"pct": pct, "value": value, "cost": cost, "net": value - cost})

    three_year_ramp_net = sum(y["net"] for y in yearly_ramp)
    three_year_ramp_cost = sum(y["cost"] for y in yearly_ramp)
    three_year_full_net = net_value_year1_full * 3
    three_year_full_cost = fern_annual_cost * 3

    three_year_net = three_year_ramp_net if use_ramp else three_year_full_net
    three_year_cost = three_year_ramp_cost if use_ramp else three_year_full_cost
    roi_3_year = (three_year_net / three_year_cost) * 100 if three_year_cost > 0 else 0

    return {
        "hourly_rate": hourly_rate,
        "current_hours_per_charge": current_hours_per_charge,
        "effective_hours_saved_per_charge": effective_hours_saved_per_charge,
        "hours_with_fern_per_charge": hours_with_fern_per_charge,
        "charges_inhouse_today": charges_inhouse_today,
        "charges_outside_today": charges_outside_today,
        "charges_inhouse_fern": charges_inhouse_fern,
        "charges_outside_fern": charges_outside_fern,
        "inhouse_labor_cost_today": inhouse_labor_cost_today,
        "inhouse_labor_cost_with_fern": inhouse_labor_cost_with_fern,
        "outside_cost_today": outside_cost_today,
        "outside_cost_with_fern": outside_cost_with_fern,
        "hours_inhouse_today": hours_inhouse_today,
        "hours_inhouse_with_fern": hours_inhouse_with_fern,
        "total_hours_saved": total_hours_saved,
        "inhouse_time_savings": inhouse_time_savings,
        "effective_outside_counsel_per_charge": effective_outside_counsel_per_charge,
        "outside_fees_savings": outside_fees_savings,
        "total_value_year1_full": total_value_year1_full,
        "fern_annual_cost": fern_annual_cost,
        "cost_without_fern": cost_without_fern,
        "cost_with_fern": cost_with_fern,
        "net_value_year1_full": net_value_year1_full,
        "payback_months": max(0, payback_months),
        "money_multiple": money_multiple,
        "yearly_ramp": yearly_ramp,
        "three_year_net": three_year_net,
        "three_year_cost": three_year_cost,
        "roi_3_year": max(0, roi_3_year),
    }


def _hex_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


_PDF_CHAR_REPLACEMENTS = {
    "—": "-",  # em dash
    "–": "-",  # en dash
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "→": "->",
}


def _pdf_safe(text):
    """Core PDF fonts (Helvetica) only support latin-1 — swap typographic
    punctuation for ASCII equivalents and drop anything else that can't encode."""
    for bad, good in _PDF_CHAR_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def build_case_study_pdf(is_law_firm, session_mode, scenario_cfg, roi, use_ramp):
    pdf = FPDF(unit="mm", format="Letter")
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.set_margins(18, 10, 18)
    pdf.add_page()

    def h1(text):
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(*_hex_rgb(FERN_FOREST))
        pdf.cell(0, 9, _pdf_safe(text), new_x="LMARGIN", new_y="NEXT")

    def h2(text):
        pdf.ln(1.2)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_hex_rgb(FERN_GREEN))
        pdf.cell(0, 5.5, _pdf_safe(text.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*_hex_rgb(FERN_PALE))
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(1)

    def body(text, size=9):
        pdf.set_font("Helvetica", "", size)
        pdf.set_text_color(60, 60, 56)
        pdf.multi_cell(0, 4.2, _pdf_safe(text))

    def kv_row(label, value):
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(90, 90, 86)
        pdf.cell(85, 5.2, _pdf_safe(label))
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_hex_rgb(FERN_FOREST))
        pdf.cell(0, 5.2, _pdf_safe(value), new_x="LMARGIN", new_y="NEXT")

    # ---- Header ----
    h1("Fern")
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(90, 90, 86)
    pdf.cell(0, 6, "Personalized ROI case study", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(140, 140, 132)
    pdf.cell(0, 5, f"Generated {datetime.now().strftime('%B %d, %Y')}", new_x="LMARGIN", new_y="NEXT")

    if session_mode == "Work through this with a Fern rep" and st.session_state.lead_name.strip():
        pdf.ln(1)
        company = f" — {st.session_state.lead_company}" if st.session_state.lead_company.strip() else ""
        body(f"Prepared for: {st.session_state.lead_name} ({st.session_state.lead_email}){company}")

    # ---- Company profile ----
    h2("Company profile")
    kv_row("Buyer type", "Law firm / outside counsel" if is_law_firm else "In-house legal/HR team")
    kv_row("Industry", st.session_state.industry)
    kv_row(
        "Attorneys/staff count" if is_law_firm else "Employee headcount",
        str(st.session_state.employee_count),
    )

    # ---- Usage estimates ----
    h2("Usage estimates")
    kv_row("Charges/matters per year", str(st.session_state.charges_per_year))
    if is_law_firm:
        kv_row("Billable rate", format_currency(roi["hourly_rate"]))
    else:
        kv_row(
            "Handled in-house today",
            f"{st.session_state.inhouse_pct_today}% ({round(roi['charges_inhouse_today']):,} charges)",
        )
        kv_row(
            "Handled in-house with Fern",
            f"{st.session_state.inhouse_pct_fern}% ({round(roi['charges_inhouse_fern']):,} charges)",
        )
        kv_row("Outside counsel cost/charge", format_currency(st.session_state.outside_counsel_cost_per_charge))
        kv_row("Annual salary", format_currency(st.session_state.annual_salary))
        kv_row("Inhouse effective hourly rate", format_currency(roi["hourly_rate"]))

    # ---- Scenario ----
    h2("Scenario")
    kv_row("Current setup", scenario_cfg["label"])
    kv_row("Current time spent per charge", f"{roi['current_hours_per_charge']} hrs")
    body(scenario_cfg["note"])
    if st.session_state.setup_comments.strip():
        pdf.ln(1)
        body(f"Comments: {st.session_state.setup_comments.strip()}")

    # ---- Annual value breakdown (drawn as a bar chart) ----
    h2("Annual value breakdown")
    rows = []
    if is_law_firm:
        rows.append(("Billable capacity unlocked", roi["inhouse_time_savings"], FERN_GREEN))
    else:
        rows.append(("Inhouse time savings", roi["inhouse_time_savings"], FERN_GREEN))
        rows.append(("Outside fees savings", roi["outside_fees_savings"], FERN_PALE))
    rows.append(("Fern cost", roi["fern_annual_cost"], FERN_AMBER))
    rows.append(("Net annual value", roi["net_value_year1_full"], FERN_FOREST))

    max_amount = max(abs(amount) for _, amount, _ in rows) or 1
    label_width = 52
    bar_max_width = 90
    for label, amount, color in rows:
        y = pdf.get_y()
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(60, 60, 56)
        pdf.set_xy(pdf.l_margin, y)
        pdf.cell(label_width, 7, _pdf_safe(label))
        bar_width = max(2.0, (amount / max_amount) * bar_max_width)
        pdf.set_fill_color(*_hex_rgb(color))
        pdf.rect(pdf.l_margin + label_width, y + 1, bar_width, 5, style="F")
        pdf.set_xy(pdf.l_margin + label_width + bar_max_width + 4, y)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(26, 26, 24)
        pdf.cell(0, 7, format_currency(amount), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    # ---- Key metrics ----
    h2("Key metrics")
    kv_row("Return", f"{roi['money_multiple']:.1f}x")
    kv_row("Payback period", f"{roi['payback_months']:.1f} months")
    kv_row("3-year ROI", f"{roi['roi_3_year']:.1f}%")
    kv_row(
        f"3-year net value ({'adoption ramp' if use_ramp else 'full value'})",
        format_currency(roi["three_year_net"]),
    )

    # ---- Time saved ----
    h2("Time saved")
    kv_row("Total hours freed annually", f"{round(roi['total_hours_saved']):,} hours")
    kv_row(
        "Per-charge turnaround",
        f"~{roi['current_hours_per_charge']} hrs -> ~{roi['hours_with_fern_per_charge']:.0f} hrs with Fern",
    )

    # ---- Proof point ----
    h2("Proof point")
    body(
        "One customer's legal team went from uploading source documents to an EEOC-ready "
        "position statement in about two hours total, versus a full day or more manually. "
        "Fern's approach is shaped by a Customer Advisory Board of F-1000 senior employment "
        "lawyers."
    )

    # ---- Methodology / trust footer ----
    h2("Methodology")
    body(
        "These figures are conservative estimates for internal discussion purposes only, "
        "developed with input from Fern's Customer Advisory Board. Actual results vary by case "
        "complexity and adoption speed. This is not a guarantee. Contact sales@fernlabs.com to "
        "build a business case specific to your caseload.",
        size=8,
    )

    return bytes(pdf.output())


def build_math_text(is_law_firm, scenario_key, scenario_cfg, roi):
    """Mirrors the results UI top-to-bottom, using the same section headings and
    "Without Fern" / "With Fern" wording as the metrics and charts above it, so a
    formula is easy to find by matching it to what's on screen."""

    # ---- 1. TIME SAVED ANNUALLY (matches the "Time saved annually" metric + caption) ----
    assumptions = "\n".join(
        f"  {'-> ' if key == scenario_key else '   '}{cfg['label']}: "
        f"{cfg['current_hours_per_charge']} hrs -> {cfg['hours_with_fern_per_charge']} hrs with Fern"
        for key, cfg in SCENARIOS.items()
    )

    time_saved_section = f"""TIME SAVED ANNUALLY
Typical time spent by setup (starting suggestions, by current tool):
{assumptions}

Your entered time spent per charge: {roi['current_hours_per_charge']} hrs -> \
{roi['hours_with_fern_per_charge']:.0f} hrs with Fern (current: {scenario_cfg['label'].split(' - ', 1)[-1]})

Time saved annually = Time spent in-house without Fern - Time spent in-house with Fern
= {round(roi['hours_inhouse_today']):,} hrs - {round(roi['hours_inhouse_with_fern']):,} hrs \
= {round(roi['total_hours_saved']):,} hrs"""

    # ---- 2. ANNUAL IN-HOUSE OPERATIONS (matches the two "without Fern vs. with Fern" charts) ----
    if is_law_firm:
        operations_section = f"""TIME IN-HOUSE ANNUALLY — WITHOUT FERN VS. WITH FERN
Without Fern = matters/year x hrs spent per matter
= {round(roi['charges_inhouse_today']):,} x {roi['current_hours_per_charge']} hrs = {round(roi['hours_inhouse_today']):,} hrs
With Fern = matters/year x hrs spent per matter with Fern
= {round(roi['charges_inhouse_fern']):,} x {roi['hours_with_fern_per_charge']:.0f} hrs \
= {round(roi['hours_inhouse_with_fern']):,} hrs"""
    else:
        sentence = ""
        if (
            roi["charges_inhouse_today"] > 0
            and roi["hours_inhouse_today"] > 0
            and roi["charges_inhouse_fern"] > roi["charges_inhouse_today"]
            and roi["hours_inhouse_with_fern"] < roi["hours_inhouse_today"]
        ):
            pct_more_charges = (roi["charges_inhouse_fern"] / roi["charges_inhouse_today"] - 1) * 100
            pct_less_time = (1 - roi["hours_inhouse_with_fern"] / roi["hours_inhouse_today"]) * 100
            sentence = (
                f"\n\nWith Fern, your team handles {pct_more_charges:.0f}% more charges in-house "
                f"with {pct_less_time:.0f}% less time spent."
            )

        operations_section = f"""ANNUAL IN-HOUSE OPERATIONS — WITHOUT FERN VS. WITH FERN
Charges handled in-house
Without Fern = charges/year x % handled in-house today
= {st.session_state.charges_per_year} x {st.session_state.inhouse_pct_today}% = {round(roi['charges_inhouse_today']):,} charges
With Fern = charges/year x % handled in-house with Fern
= {st.session_state.charges_per_year} x {st.session_state.inhouse_pct_fern}% = {round(roi['charges_inhouse_fern']):,} charges

Time spent in-house
Without Fern = charges handled in-house without Fern x hrs spent per charge
= {round(roi['charges_inhouse_today']):,} x {roi['current_hours_per_charge']} hrs = {round(roi['hours_inhouse_today']):,} hrs
With Fern = charges handled in-house with Fern x hrs spent per charge with Fern
= {round(roi['charges_inhouse_fern']):,} x {roi['hours_with_fern_per_charge']:.0f} hrs \
= {round(roi['hours_inhouse_with_fern']):,} hrs{sentence}"""

    # ---- 3. YEAR 1 NET SAVINGS / NET VALUE (matches the metric + return/payback/ROI) ----
    rate_line = (
        ""
        if is_law_firm
        else f"""Inhouse effective hourly rate = (annual salary x {LOADED_COST_MULTIPLIER}) / {WORK_HOURS_PER_YEAR:,} hrs/yr
= ({format_currency(st.session_state.annual_salary)} x {LOADED_COST_MULTIPLIER}) / {WORK_HOURS_PER_YEAR:,} \
= {format_currency(roi['hourly_rate'])}/hr

"""
    )

    value_label = "Year 1 net value" if is_law_firm else "Year 1 net savings"
    rate_term = "billable rate" if is_law_firm else "inhouse effective hourly rate"
    inhouse_value_label = "Billable capacity unlocked" if is_law_firm else "Inhouse time savings"
    net_savings_section = f"""{value_label.upper()}
{rate_line}{inhouse_value_label} = time saved annually x {rate_term}
= {round(roi['total_hours_saved']):,} x {format_currency(roi['hourly_rate'])} = {format_currency(roi['inhouse_time_savings'])}"""

    if is_law_firm:
        net_savings_section += f"""

Total value = Billable capacity unlocked
= {format_currency(roi['total_value_year1_full'])}"""
    else:
        net_savings_section += f"""

Outside fees savings = outside counsel cost without Fern - outside counsel cost with Fern
= {format_currency(roi['outside_cost_today'])} - {format_currency(roi['outside_cost_with_fern'])} \
= {format_currency(roi['outside_fees_savings'])}

Total value = Inhouse time savings + Outside fees savings
= {format_currency(roi['inhouse_time_savings'])} + {format_currency(roi['outside_fees_savings'])} \
= {format_currency(roi['total_value_year1_full'])}"""

    net_savings_section += f"""

{value_label} = Total value - Fern annual cost
= {format_currency(roi['total_value_year1_full'])} - {format_currency(roi['fern_annual_cost'])} \
= {format_currency(roi['net_value_year1_full'])}

Return = Total value / Fern annual cost
= {format_currency(roi['total_value_year1_full'])} / {format_currency(roi['fern_annual_cost'])} \
= {roi['money_multiple']:.1f}x

Payback period = Fern annual cost / (Total value / 12)
= {format_currency(roi['fern_annual_cost'])} / ({format_currency(roi['total_value_year1_full'])} / 12) \
= {roi['payback_months']:.1f} months

3-year ROI = (3-year net value / 3-year Fern cost) x 100
= ({format_currency(roi['three_year_net'])} / {format_currency(roi['three_year_cost'])}) x 100 \
= {roi['roi_3_year']:.1f}%"""

    # ---- 4. ANNUAL COST — WITHOUT FERN VS. WITH FERN (matches the second chart card) ----
    if is_law_firm:
        cost_section = f"""ANNUAL COST — WITHOUT FERN VS. WITH FERN
Without Fern = matters/year x hrs spent per matter x billable rate
= {round(roi['charges_inhouse_today']):,} x {roi['current_hours_per_charge']} hrs x \
{format_currency(roi['hourly_rate'])} = {format_currency(roi['cost_without_fern'])}

With Fern = matters/year x hrs spent per matter with Fern x billable rate + Fern annual cost
= {round(roi['charges_inhouse_fern']):,} x {roi['hours_with_fern_per_charge']:.0f} hrs x \
{format_currency(roi['hourly_rate'])} + {format_currency(roi['fern_annual_cost'])} \
= {format_currency(roi['cost_with_fern'])}"""
    else:
        cost_section = f"""ANNUAL COST — WITHOUT FERN VS. WITH FERN
Without Fern = in-house cost + outside counsel cost
  In-house: {round(roi['charges_inhouse_today']):,} charges x {roi['current_hours_per_charge']} hrs x \
{format_currency(roi['hourly_rate'])} = {format_currency(roi['inhouse_labor_cost_today'])}
  Outside: {round(roi['charges_outside_today']):,} charges x {format_currency(roi['effective_outside_counsel_per_charge'])} \
= {format_currency(roi['outside_cost_today'])}
= {format_currency(roi['inhouse_labor_cost_today'])} + {format_currency(roi['outside_cost_today'])} \
= {format_currency(roi['cost_without_fern'])}

With Fern = in-house cost + outside counsel cost + Fern annual cost
  In-house: {round(roi['charges_inhouse_fern']):,} charges x {roi['hours_with_fern_per_charge']:.0f} hrs x \
{format_currency(roi['hourly_rate'])} = {format_currency(roi['inhouse_labor_cost_with_fern'])}
  Outside: {round(roi['charges_outside_fern']):,} charges x {format_currency(roi['effective_outside_counsel_per_charge'])} \
= {format_currency(roi['outside_cost_with_fern'])}
= {format_currency(roi['inhouse_labor_cost_with_fern'])} + {format_currency(roi['outside_cost_with_fern'])} + \
{format_currency(roi['fern_annual_cost'])} = {format_currency(roi['cost_with_fern'])}"""

    cost_section += f"""

Net value = Annual cost without Fern - Annual cost with Fern
= {format_currency(roi['cost_without_fern'])} - {format_currency(roi['cost_with_fern'])} \
= {format_currency(roi['net_value_year1_full'])}"""

    return f"""{time_saved_section}

{operations_section}

{net_savings_section}

{cost_section}""".strip()


def notify_slack(is_law_firm, session_mode, scenario_cfg, roi):
    """Post a no-PII summary of a case-study download to Slack, if configured.

    Deliberately excludes lead_name/lead_email/lead_company — the point is to see
    what customers are seeing without collecting personal data on the backend.
    """
    try:
        webhook_url = st.secrets.get("SLACK_WEBHOOK_URL", "")
    except st.errors.StreamlitSecretNotFoundError:
        return  # no secrets.toml configured at all — nothing to notify
    if not webhook_url:
        return

    split_line = (
        f"\n*Charge split:* {st.session_state.inhouse_pct_today}% in-house today -> "
        f"{st.session_state.inhouse_pct_fern}% in-house with Fern"
        if not is_law_firm
        else ""
    )

    text = (
        ":inbox_tray: *Fern ROI case study downloaded*\n"
        "_No name/email captured — self-serve download._\n\n"
        f"*Buyer type:* {'Law firm / outside counsel' if is_law_firm else 'In-house legal/HR team'}\n"
        f"*Session:* {session_mode}\n"
        f"*Industry:* {st.session_state.industry}\n"
        f"*Scenario:* {scenario_cfg['label']}\n"
        f"*Charges/matters per year:* {st.session_state.charges_per_year}"
        f"{split_line}\n"
        f"*Net value (Year 1):* {format_currency(roi['net_value_year1_full'])}\n"
        f"*3-year ROI:* {roi['roi_3_year']:.1f}%\n"
        f"*Payback period:* {roi['payback_months']:.1f} months\n"
        f"*Downloaded:* {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )

    try:
        requests.post(webhook_url, json={"text": text}, timeout=5)
    except requests.RequestException:
        pass  # never let a notification failure block the user's download


@st.dialog("Request a trial", width="large")
def request_trial_dialog():
    st.iframe("https://tally.so/r/0QDaeQ", height=700)


# ---- Header --------------------------------------------------------------
st.title("Fern ROI calculator", text_alignment="center")
st.caption("See your personalized value on employment charges and demand letters", text_alignment="center")

# ---- Buyer segmentation ---------------------------------------------------
with st.container(border=True):
    st.subheader("Who are you?")
    buyer_type = st.segmented_control(
        "Buyer type",
        ["In-house legal/HR team", "Law firm / outside counsel"],
        key="buyer_type",
        label_visibility="collapsed",
        width="stretch",
    )
    is_law_firm = buyer_type == "Law firm / outside counsel"
    st.caption(
        "Measures value as billable capacity unlocked" if is_law_firm else "Measures value as cost avoided"
    )

# ---- Scenario selector -----------------------------------------------------
scenario_keys = list(SCENARIOS)
scenario_labels = [SCENARIOS[k]["label"] for k in scenario_keys]

with st.container(border=True):
    st.subheader("Which best describes your current setup?")
    scenario_label = st.radio(
        "Current setup",
        scenario_labels,
        key="scenario_label",
        on_change=sync_hours_to_scenario,
        label_visibility="collapsed",
    )
    scenario_key = scenario_keys[scenario_labels.index(scenario_label)] if scenario_label else scenario_keys[0]
    scenario_cfg = SCENARIOS[scenario_key]
    st.caption(f":material/info: {scenario_cfg['note']}")

    st.number_input(
        "Current estimate of time spent per charge (hrs)",
        min_value=0,
        step=1,
        key="current_hours_per_charge",
        help="Your own real-world estimate of how many hours it takes today to handle "
        "one charge, start to finish. This is what drives the ROI math below — edit it "
        "to match your actual experience.",
    )
    st.caption(
        "Pre-filled based on your answer above — edit this to your own number, "
        "it's what the ROI calculation actually uses."
    )

    st.text_area(
        "Comments",
        key="setup_comments",
        placeholder="Include any comments about your current tool usage or productivity",
    )

# ---- Session mode ----------------------------------------------------------
with st.container(border=True):
    st.subheader("How do you want to use this?")
    session_mode = st.segmented_control(
        "Session mode",
        ["Self-serve preview", "Work through this with a Fern rep"],
        key="session_mode",
        label_visibility="collapsed",
        width="stretch",
    )
    if session_mode == "Work through this with a Fern rep":
        st.caption("Build the business case together, get a copy sent to you.")
    else:
        st.caption("Instant results, download anytime.")

left, right = st.columns(2, gap="large")

# ---- Input section -----------------------------------------------------
with left:
    with st.container(border=True):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.subheader("Your details")
            st.button("Reset", icon=":material/refresh:", on_click=reset_inputs, key="reset_button")

        st.selectbox(
            "Industry",
            ["Technology", "Financial Services", "Healthcare", "Manufacturing", "Retail", "Other"],
            key="industry",
        )

        st.text_input(
            "Attorneys/staff count" if is_law_firm else "Employee headcount",
            key="employee_count",
        )

        st.markdown("**" + ("Practice volume" if is_law_firm else "Legal operations") + "**")

        st.slider(
            "Employment matters per year" if is_law_firm else "Charges/cases per year",
            min_value=0,
            max_value=1000,
            step=5,
            key="charges_per_year",
            help="How many employment matters your firm handles per year, across all attorneys."
            if is_law_firm
            else "How many EEOC charges, demand letters, or similar employment disputes your "
            "team handles per year. Count anything that currently requires drafting a position "
            "statement or formal response — this drives every other number below.",
        )

        if not is_law_firm:
            st.slider(
                "% of charges handled in-house today",
                min_value=0,
                max_value=100,
                step=5,
                key="inhouse_pct_today",
                format="%d%%",
                help="What share of your charges your own team handles today, versus sending "
                "to outside counsel. This sets the 'without Fern' baseline cost.",
            )
            charges_inhouse_today_n = round(st.session_state.charges_per_year * st.session_state.inhouse_pct_today / 100)
            charges_outside_today_n = st.session_state.charges_per_year - charges_inhouse_today_n
            st.caption(
                f"Today: {st.session_state.inhouse_pct_today}% in-house ({charges_inhouse_today_n:,} charges) · "
                f"{100 - st.session_state.inhouse_pct_today}% outside counsel ({charges_outside_today_n:,} charges)"
            )

            st.slider(
                "% of charges you'd handle in-house with Fern",
                min_value=0,
                max_value=100,
                step=5,
                key="inhouse_pct_fern",
                format="%d%%",
                help="Because Fern makes in-house work much faster, most teams can bring "
                "nearly everything in-house instead of sending it to outside counsel — "
                "defaults to 100%. Lower it if you'd still route some complex or "
                "high-risk charges to outside counsel even with Fern.",
            )
            charges_inhouse_fern_n = round(st.session_state.charges_per_year * st.session_state.inhouse_pct_fern / 100)
            charges_outside_fern_n = st.session_state.charges_per_year - charges_inhouse_fern_n
            st.caption(
                f"With Fern: {st.session_state.inhouse_pct_fern}% in-house ({charges_inhouse_fern_n:,} charges) · "
                f"{100 - st.session_state.inhouse_pct_fern}% outside counsel ({charges_outside_fern_n:,} charges)"
            )

            st.slider(
                "Outside counsel cost per charge",
                min_value=0,
                max_value=30000,
                step=500,
                key="outside_counsel_cost_per_charge",
                format="$%d",
                help="What you currently pay an outside law firm, on average, to handle one "
                "charge from intake to resolution — legal fees only, not settlements or "
                "damages. Typical range: $10K–$20K per charge, 20–60 billed hours. Check a "
                "recent invoice if you're not sure.",
            )

        if is_law_firm:
            st.slider(
                "Billable rate",
                min_value=0,
                max_value=1000,
                step=5,
                key="hourly_labor_cost",
                format="$%d",
                help="The rate you bill clients for this work — used to value the hours Fern frees up.",
            )
        else:
            st.slider(
                "Annual salary",
                min_value=30_000,
                max_value=500_000,
                step=1000,
                key="annual_salary",
                format="$%d",
                help="The base annual salary of the person (or role) doing this work. We convert "
                "this to a fully-loaded hourly rate below — used to value the hours Fern frees up "
                "for charges handled in-house.",
            )
            st.caption(
                f"≈ {format_currency(inhouse_hourly_rate())}/hr fully loaded "
                f"(salary × {LOADED_COST_MULTIPLIER} for benefits/overhead ÷ {WORK_HOURS_PER_YEAR:,} hrs/yr)"
            )

    with st.container(border=True):
        st.subheader("Fern pricing")
        pricing_model = st.segmented_control(
            "Pricing model",
            ["Per charge", "Monthly"],
            key="pricing_model",
            label_visibility="collapsed",
        )
        if pricing_model == "Per charge":
            st.caption(f"${st.session_state.fern_cost_per_charge}/charge")
        else:
            st.slider("Monthly cost", min_value=0, max_value=20000, step=100, key="fern_monthly_fixed", format="$%d")

roi = calculate_roi(is_law_firm, scenario_cfg, pricing_model or "Per charge", st.session_state.use_ramp)

# ---- Results section -----------------------------------------------------
with right:
    with st.container(border=True):
        st.subheader("Your Business Impact Results")

        st.metric(
            "Time saved annually",
            f"{round(roi['total_hours_saved']):,} hours",
            border=True,
        )
        scenario_short_label = scenario_cfg["label"].split(" - ", 1)[-1]
        st.caption(
            f"Each {'matter' if is_law_firm else 'in-house charge'} drops from "
            f"~{roi['current_hours_per_charge']} hrs to ~{roi['hours_with_fern_per_charge']:.0f} hrs with Fern "
            f"(current: {scenario_short_label})"
        )

        st.markdown(
            "**Annual in-house operations — without Fern vs. with Fern**"
            if not is_law_firm
            else "**Time in-house annually — without Fern vs. with Fern**"
        )

        if not is_law_firm:
            st.caption("Charges handled in-house")
            charge_rows = [
                ("Without Fern", roi["charges_inhouse_today"], FERN_AMBER),
                ("With Fern", roi["charges_inhouse_fern"], FERN_GREEN),
            ]
            st.altair_chart(
                breakdown_chart(charge_rows, value_format=",.0f", value_prefix="", value_suffix=" charges"),
                width="stretch",
            )
            st.caption("Time spent in-house")

        hours_rows = [
            ("Without Fern", roi["hours_inhouse_today"], FERN_AMBER),
            ("With Fern", roi["hours_inhouse_with_fern"], FERN_GREEN),
        ]
        st.altair_chart(
            breakdown_chart(hours_rows, value_format=",.0f", value_prefix="", value_suffix=" hrs"),
            width="stretch",
        )

        if (
            not is_law_firm
            and roi["charges_inhouse_today"] > 0
            and roi["hours_inhouse_today"] > 0
            and roi["charges_inhouse_fern"] > roi["charges_inhouse_today"]
            and roi["hours_inhouse_with_fern"] < roi["hours_inhouse_today"]
        ):
            pct_more_charges = (roi["charges_inhouse_fern"] / roi["charges_inhouse_today"] - 1) * 100
            pct_less_time = (1 - roi["hours_inhouse_with_fern"] / roi["hours_inhouse_today"]) * 100
            st.caption(
                f"With Fern, your team handles {pct_more_charges:.0f}% more charges in-house "
                f"with {pct_less_time:.0f}% less time spent."
            )

        st.metric(
            "Year 1 net value" if is_law_firm else "Year 1 net savings",
            format_currency(roi["net_value_year1_full"]),
            border=True,
        )
        st.caption(
            f"≈ {roi['money_multiple']:.1f}x return — every $1 spent on Fern returns "
            f"about ${roi['money_multiple']:.1f}"
        )
        if is_law_firm:
            st.caption("Assumes freed hours convert to billed work at your stated rate.")

        with st.container(horizontal=True):
            st.metric("Payback period", f"{roi['payback_months']:.1f} mo", border=True)
            st.metric("3-year ROI", f"{roi['roi_3_year']:.1f}%", border=True)

        st.toggle(
            "Use conservative 3-year adoption ramp (40% → 70% → 100%) instead of full value from Year 1",
            key="use_ramp",
        )

        if session_mode == "Work through this with a Fern rep":
            with st.container(border=True):
                st.markdown(":material/mail: **Get this sent to you**")
                st.text_input("Your name", key="lead_name", placeholder="Your name")
                st.text_input("Work email", key="lead_email", placeholder="Work email")
                st.text_input("Company (optional)", key="lead_company", placeholder="Company (optional)")
                st.caption("A Fern rep will follow up within 1 business day to refine this together.")

        can_download = session_mode == "Self-serve preview" or (
            st.session_state.lead_name.strip() and st.session_state.lead_email.strip()
        )

        downloaded = st.download_button(
            "Get my case study" if session_mode == "Work through this with a Fern rep" else "Download case study",
            data=build_case_study_pdf(is_law_firm, session_mode, scenario_cfg, roi, st.session_state.use_ramp),
            file_name=f"fern-roi-case-study-{st.session_state.industry}-{'lawfirm' if is_law_firm else 'inhouse'}.pdf",
            mime="application/pdf",
            disabled=not can_download,
            icon=":material/download:",
            width="stretch",
            type="primary",
        )
        if downloaded:
            notify_slack(is_law_firm, session_mode, scenario_cfg, roi)

    # ---- Savings breakdown ----
    with st.container(border=True):
        st.subheader("Annual cost — without Fern vs. with Fern")

        cost_rows = [
            ("Without Fern", roi["cost_without_fern"], FERN_AMBER),
            ("With Fern", roi["cost_with_fern"], FERN_GREEN),
        ]
        st.altair_chart(breakdown_chart(cost_rows), width="stretch")

        pct_reduction = (
            (roi["cost_without_fern"] - roi["cost_with_fern"]) / roi["cost_without_fern"] * 100
            if roi["cost_without_fern"] > 0
            else 0
        )
        st.caption(
            f"Fern saves {format_currency(roi['net_value_year1_full'])} per year — "
            f"a {pct_reduction:.0f}% reduction versus handling this caseload without it."
        )

        if st.session_state.use_ramp:
            st.markdown("**3-year adoption ramp — net value**")
            ramp_colors = [FERN_PALE, FERN_GREEN, FERN_FOREST]
            ramp_rows = [
                (f"Year {i + 1} ({y['pct'] * 100:.0f}% adoption)", y["net"], ramp_colors[i])
                for i, y in enumerate(roi["yearly_ramp"])
            ]
            st.altair_chart(breakdown_chart(ramp_rows), width="stretch")

    # ---- Proof point ----
    with st.container(border=True):
        st.caption("PROOF POINT")
        st.write(
            "One customer's legal team went from uploading source documents to an EEOC-ready "
            "position statement in about two hours total — down from a full day or more done manually."
        )
        st.caption("Shaped by our Customer Advisory Board of F-1000 senior employment lawyers.")

    # ---- Show the math ----
    with st.expander("Show the math", icon=":material/functions:"):
        st.code(build_math_text(is_law_firm, scenario_key, scenario_cfg, roi), language=None)

# ---- Methodology / trust footer -----------------------------------------
with st.container(border=True):
    st.markdown("**Methodology**")
    st.caption(
        "These figures are conservative estimates for internal discussion purposes only, developed with input "
        "from Fern's Customer Advisory Board of F-1000 senior employment lawyers. They are not a guarantee — "
        "actual results vary by case complexity, document volume, and how quickly your team adopts the tool. "
        "Contact **sales@fernlabs.com** to build a business case specific to your caseload."
    )

with st.container(horizontal_alignment="center"):
    st.space("medium")
    if st.button("Request a trial", icon=":material/rocket_launch:", type="primary", width="content"):
        request_trial_dialog()
