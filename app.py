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

st.logo("assets/fern-logo.svg", link="https://www.fernlabs.ai", size="large")

# ---- Scenario configs -------------------------------------------------
# hours_saved_per_charge is Fern's assumed savings vs. the 20 hr/charge baseline,
# for each starting-point tool (this is the "Fern savings assumption" per scenario).
SCENARIOS = {
    "baseline": {
        "label": "Starting from scratch",
        "hours_saved_per_charge": 18,
        "outside_counsel_multiplier": 1.0,
        "note": "No existing AI tool for employment disputes — Fern delivers full value.",
    },
    "existing": {
        "label": "Already have an in-house legal tool",
        "hours_saved_per_charge": 15,
        "outside_counsel_multiplier": 0.97,
        "note": "General-purpose or in-house tools help a little with drafting and research, "
        "but aren't purpose-built for employment law charges — your team still does "
        "significant manual review, and reliance on outside counsel stays about the same.",
    },
}

HOURS_PER_CHARGE_BASE = 20
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
    "scenario_label": SCENARIOS["baseline"]["label"],
    "use_ramp": False,
    "pricing_model": "Per charge",
    "industry": "Technology",
    "employee_count": 50,
    "annual_revenue": 5_000_000,
    "charges_per_year": 120,
    "inhouse_pct": 75,
    "outside_counsel_cost_per_charge": 15000,
    "annual_salary": 192_000,
    "hourly_labor_cost": 150,
    "fern_cost_per_charge": 900,
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


def format_currency(num):
    return f"${round(num):,}"


def breakdown_chart(rows):
    """Horizontal bar chart for a small set of named dollar amounts.

    rows: list of (label, amount, color) tuples, in top-to-bottom display order.
    """
    df = pd.DataFrame(rows, columns=["Category", "Amount", "Color"])
    order = df["Category"].tolist()
    colors = df["Color"].tolist()

    bars = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, height=26)
        .encode(
            x=alt.X("Amount:Q", title=None, axis=alt.Axis(format="$,.0f", grid=False)),
            y=alt.Y("Category:N", title=None, sort=order, axis=alt.Axis(labelLimit=160)),
            color=alt.Color("Category:N", scale=alt.Scale(domain=order, range=colors), legend=None),
            tooltip=[
                alt.Tooltip("Category:N", title="Category"),
                alt.Tooltip("Amount:Q", title="Amount", format="$,.0f"),
            ],
        )
    )
    labels = (
        alt.Chart(df)
        .mark_text(align="left", dx=6, color="#1a1a18")
        .encode(
            x=alt.X("Amount:Q"),
            y=alt.Y("Category:N", sort=order),
            text=alt.Text("Amount:Q", format="$,.0f"),
        )
    )
    return (bars + labels).properties(height=len(df) * 42 + 20)


def calculate_roi(is_law_firm, scenario_cfg, pricing_model, use_ramp):
    charges_per_year = st.session_state.charges_per_year
    outside_counsel_cost_per_charge = st.session_state.outside_counsel_cost_per_charge
    fern_cost_per_charge = st.session_state.fern_cost_per_charge
    fern_monthly_fixed = st.session_state.fern_monthly_fixed
    inhouse_pct = st.session_state.inhouse_pct / 100

    effective_hours_saved_per_charge = scenario_cfg["hours_saved_per_charge"]
    hours_with_fern_per_charge = HOURS_PER_CHARGE_BASE - effective_hours_saved_per_charge
    effective_outside_counsel_per_charge = outside_counsel_cost_per_charge * scenario_cfg["outside_counsel_multiplier"]

    if is_law_firm:
        # A law firm IS outside counsel, so every matter is "in-house" to the firm —
        # there's no split, and hours freed are billable capacity unlocked, not cost avoided.
        # Billable rate is a direct client-billing rate, not derived from a salary.
        hourly_rate = st.session_state.hourly_labor_cost
        charges_inhouse = charges_per_year
        charges_outside = 0
        total_hours_saved = charges_inhouse * effective_hours_saved_per_charge
        inhouse_time_savings = total_hours_saved * hourly_rate
        outside_fees_savings = 0
    else:
        # In-house: charges split between work handled internally (time saved, valued at
        # the fully-loaded hourly rate derived from salary) and work sent to outside counsel
        # (fee avoided entirely).
        hourly_rate = inhouse_hourly_rate()
        charges_inhouse = charges_per_year * inhouse_pct
        charges_outside = charges_per_year - charges_inhouse
        total_hours_saved = charges_inhouse * effective_hours_saved_per_charge
        inhouse_time_savings = total_hours_saved * hourly_rate
        outside_fees_savings = charges_outside * effective_outside_counsel_per_charge

    total_value_year1_full = inhouse_time_savings + outside_fees_savings

    fern_annual_cost = (
        charges_per_year * fern_cost_per_charge
        if pricing_model == "Per charge"
        else (fern_monthly_fixed or 3000) * 12
    )

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
        "effective_hours_saved_per_charge": effective_hours_saved_per_charge,
        "hours_with_fern_per_charge": hours_with_fern_per_charge,
        "charges_inhouse": charges_inhouse,
        "charges_outside": charges_outside,
        "total_hours_saved": total_hours_saved,
        "inhouse_time_savings": inhouse_time_savings,
        "effective_outside_counsel_per_charge": effective_outside_counsel_per_charge,
        "outside_fees_savings": outside_fees_savings,
        "total_value_year1_full": total_value_year1_full,
        "fern_annual_cost": fern_annual_cost,
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
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(18, 14, 18)
    pdf.add_page()

    def h1(text):
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(*_hex_rgb(FERN_FOREST))
        pdf.cell(0, 9, _pdf_safe(text), new_x="LMARGIN", new_y="NEXT")

    def h2(text):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_hex_rgb(FERN_GREEN))
        pdf.cell(0, 6, _pdf_safe(text.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*_hex_rgb(FERN_PALE))
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(1.5)

    def body(text, size=9):
        pdf.set_font("Helvetica", "", size)
        pdf.set_text_color(60, 60, 56)
        pdf.multi_cell(0, 4.5, _pdf_safe(text))

    def kv_row(label, value):
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(90, 90, 86)
        pdf.cell(85, 5.5, _pdf_safe(label))
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_hex_rgb(FERN_FOREST))
        pdf.cell(0, 5.5, _pdf_safe(value), new_x="LMARGIN", new_y="NEXT")

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
        "Attorneys/staff count" if is_law_firm else "Employee count",
        f"{st.session_state.employee_count:,}",
    )
    kv_row("Annual revenue", format_currency(st.session_state.annual_revenue))

    # ---- Usage estimates ----
    h2("Usage estimates")
    kv_row("Charges/matters per year", str(st.session_state.charges_per_year))
    if is_law_firm:
        kv_row("Billable rate", format_currency(roi["hourly_rate"]))
    else:
        kv_row("Handled in-house", f"{st.session_state.inhouse_pct}% ({round(roi['charges_inhouse']):,} charges)")
        kv_row(
            "Outside counsel",
            f"{100 - st.session_state.inhouse_pct}% ({round(roi['charges_outside']):,} charges)",
        )
        kv_row("Outside counsel cost/charge", format_currency(st.session_state.outside_counsel_cost_per_charge))
        kv_row("Annual salary", format_currency(st.session_state.annual_salary))
        kv_row("Inhouse effective hourly rate", format_currency(roi["hourly_rate"]))

    # ---- Scenario ----
    h2("Scenario")
    kv_row("Current setup", scenario_cfg["label"])
    body(scenario_cfg["note"])

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
        f"~{HOURS_PER_CHARGE_BASE} hrs -> ~{roi['hours_with_fern_per_charge']:.0f} hrs with Fern",
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
    assumptions = "\n".join(
        f"  {'-> ' if key == scenario_key else '   '}{cfg['label']}: {cfg['hours_saved_per_charge']} hrs saved "
        f"(of {HOURS_PER_CHARGE_BASE} hr baseline)"
        for key, cfg in SCENARIOS.items()
    )

    rate_line = (
        ""
        if is_law_firm
        else f"""Inhouse effective hourly rate = (annual salary x {LOADED_COST_MULTIPLIER}) / {WORK_HOURS_PER_YEAR:,} hrs/yr
= ({format_currency(st.session_state.annual_salary)} x {LOADED_COST_MULTIPLIER}) / {WORK_HOURS_PER_YEAR:,} \
= {format_currency(roi['hourly_rate'])}/hr

"""
    )

    hours_line = (
        f"Hours saved = matters/year x hours saved per charge\n"
        f"= {round(roi['charges_inhouse']):,} x {roi['effective_hours_saved_per_charge']:.1f} hrs "
        f"= {round(roi['total_hours_saved']):,} hrs"
        if is_law_firm
        else f"Hours saved = in-house charges x hours saved per charge\n"
        f"= {round(roi['charges_inhouse']):,} x {roi['effective_hours_saved_per_charge']:.1f} hrs "
        f"= {round(roi['total_hours_saved']):,} hrs"
    )

    inhouse_line = (
        f"{'Billable capacity unlocked' if is_law_firm else 'Inhouse time savings'} = hours saved x "
        f"{'billable rate' if is_law_firm else 'inhouse effective hourly rate'}\n"
        f"= {round(roi['total_hours_saved']):,} x {format_currency(roi['hourly_rate'])} "
        f"= {format_currency(roi['inhouse_time_savings'])}"
    )

    outside_block = (
        ""
        if is_law_firm
        else f"""

Outside fees savings = outside-counsel charges x cost per charge
= {round(roi['charges_outside']):,} x {format_currency(roi['effective_outside_counsel_per_charge'])} \
= {format_currency(roi['outside_fees_savings'])}

Total value = Inhouse time savings + Outside fees savings
= {format_currency(roi['inhouse_time_savings'])} + {format_currency(roi['outside_fees_savings'])} \
= {format_currency(roi['total_value_year1_full'])}"""
    )

    total_value_line = (
        f"\n\nTotal value = Billable capacity unlocked\n= {format_currency(roi['total_value_year1_full'])}"
        if is_law_firm
        else ""
    )

    return f"""FERN SAVINGS ASSUMPTIONS (hours saved per charge, by current tool)
{assumptions}

{rate_line}{hours_line}

{inhouse_line}{outside_block}{total_value_line}

Net value = Total value - Fern annual cost
= {format_currency(roi['total_value_year1_full'])} - {format_currency(roi['fern_annual_cost'])} \
= {format_currency(roi['net_value_year1_full'])}

Payback period = Fern annual cost / (Total value / 12)
= {format_currency(roi['fern_annual_cost'])} / ({format_currency(roi['total_value_year1_full'])} / 12) \
= {roi['payback_months']:.1f} months

3-year ROI = (3-year net value / 3-year Fern cost) x 100
= ({format_currency(roi['three_year_net'])} / {format_currency(roi['three_year_cost'])}) x 100 \
= {roi['roi_3_year']:.1f}%""".strip()


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
        f"\n*Charge split:* {st.session_state.inhouse_pct}% in-house / "
        f"{100 - st.session_state.inhouse_pct}% outside counsel"
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
    scenario_label = st.segmented_control(
        "Current setup",
        scenario_labels,
        key="scenario_label",
        label_visibility="collapsed",
        width="stretch",
    )
    scenario_key = scenario_keys[scenario_labels.index(scenario_label)] if scenario_label else "baseline"
    scenario_cfg = SCENARIOS[scenario_key]
    st.caption(f":material/info: {scenario_cfg['note']}")

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

        st.number_input(
            "Attorneys/staff count" if is_law_firm else "Employee count",
            min_value=0,
            step=1,
            key="employee_count",
        )

        st.number_input("Annual revenue", min_value=0, step=1000, key="annual_revenue")

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
                "% of charges handled in-house",
                min_value=0,
                max_value=100,
                step=5,
                key="inhouse_pct",
                format="%d%%",
                help="What share of your charges your own team handles, versus sending to "
                "outside counsel. In-house charges save time (valued at your effective hourly "
                "rate below); charges sent to outside counsel instead save that firm's fee "
                "entirely, since Fern lets you bring the work in-house.",
            )
            charges_inhouse_n = round(st.session_state.charges_per_year * st.session_state.inhouse_pct / 100)
            charges_outside_n = st.session_state.charges_per_year - charges_inhouse_n
            st.caption(
                f"{st.session_state.inhouse_pct}% in-house ({charges_inhouse_n:,} charges) · "
                f"{100 - st.session_state.inhouse_pct}% outside counsel ({charges_outside_n:,} charges)"
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

        st.markdown("**Fern pricing**")
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
        st.subheader("Your ROI results")

        st.metric(
            "Time saved annually",
            f"{round(roi['total_hours_saved']):,} hours",
            border=True,
        )
        st.caption(
            f"Each {'matter' if is_law_firm else 'in-house charge'} drops from ~{HOURS_PER_CHARGE_BASE} hrs to "
            f"~{roi['hours_with_fern_per_charge']:.0f} hrs with Fern ({scenario_cfg['label']})"
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
        st.subheader("Annual " + ("value" if is_law_firm else "savings") + " breakdown")

        rows = []
        if is_law_firm:
            rows.append(("Billable capacity unlocked", roi["inhouse_time_savings"], FERN_GREEN))
        else:
            rows.append(("Inhouse time savings", roi["inhouse_time_savings"], FERN_GREEN))
            rows.append(("Outside fees savings", roi["outside_fees_savings"], FERN_PALE))
        rows.append(("Fern cost", roi["fern_annual_cost"], FERN_AMBER))
        rows.append(("Net annual value", roi["net_value_year1_full"], FERN_FOREST))

        st.altair_chart(breakdown_chart(rows), width="stretch")

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
