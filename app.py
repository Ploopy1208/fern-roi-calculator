import streamlit as st
from datetime import date

st.set_page_config(
    page_title="Fern Labs ROI calculator",
    page_icon=":material/calculate:",
    layout="wide",
)

# ---- Scenario configs -------------------------------------------------
SCENARIOS = {
    "baseline": {
        "label": "Starting from scratch",
        "hours_multiplier": 1.0,
        "outside_counsel_multiplier": 1.0,
        "note": "No existing AI tool for employment disputes — Fern delivers full value.",
    },
    "copilot": {
        "label": "Already have Microsoft CoPilot",
        "hours_multiplier": 0.85,
        "outside_counsel_multiplier": 1.0,
        "note": "CoPilot isn't fine-tuned on employment law and can misread legal terms or "
        "invent facts, so it saves a little drafting time but rarely reduces reliance on "
        "outside counsel.",
    },
    "harvey": {
        "label": "Already have Harvey",
        "hours_multiplier": 0.7,
        "outside_counsel_multiplier": 0.95,
        "note": "General legal AI can speed up research and orientation, but unreliable "
        "citations mean your team still verifies most output by hand.",
    },
}

# ---- Company presets (in-house buyer only) -----------------------------
PRESETS = {
    "largeTech": {
        "label": "Large tech enterprise",
        "industry": "Technology",
        "employee_count": 8000,
        "annual_revenue": 15_000_000_000,
        "charges_per_year": 260,
        "outside_counsel_cost_per_charge": 18000,
        "hourly_labor_cost": 220,
    },
    "smallTech": {
        "label": "Small tech company",
        "industry": "Technology",
        "employee_count": 180,
        "annual_revenue": 40_000_000,
        "charges_per_year": 12,
        "outside_counsel_cost_per_charge": 12000,
        "hourly_labor_cost": 150,
    },
    "largeHourly": {
        "label": "Large hourly workforce",
        "industry": "Manufacturing",
        "employee_count": 45000,
        "annual_revenue": 90_000_000_000,
        "charges_per_year": 550,
        "outside_counsel_cost_per_charge": 14000,
        "hourly_labor_cost": 120,
    },
}

# ---- Proof point logos (F-1000 customer advisory board, per sales deck) -
LOGOS = ["Tesla", "Cisco", "Citibank", "GKN Aerospace", "Oracle", "Under Armour", "Adobe", "Walmart", "Intuit", "Lucid"]

HOURS_PER_CHARGE_BASE = 20
HOURS_WITH_FERN_PER_CHARGE = 2
RAMP_PCT = [0.4, 0.7, 1.0]

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
    "outside_counsel_cost_per_charge": 15000,
    "hourly_labor_cost": 150,
    "fern_cost_per_charge": 900,
    "fern_monthly_fixed": 3000,
    "lead_name": "",
    "lead_email": "",
    "lead_company": "",
}

for _key, _value in DEFAULTS.items():
    st.session_state.setdefault(_key, _value)


def apply_preset(key):
    preset = PRESETS[key]
    for field in ["industry", "employee_count", "annual_revenue", "charges_per_year",
                  "outside_counsel_cost_per_charge", "hourly_labor_cost"]:
        st.session_state[field] = preset[field]


def reset_inputs():
    for key, value in DEFAULTS.items():
        st.session_state[key] = value


def format_currency(num):
    return f"${round(num):,}"


def calculate_roi(is_law_firm, scenario_cfg, pricing_model, use_ramp):
    charges_per_year = st.session_state.charges_per_year
    outside_counsel_cost_per_charge = st.session_state.outside_counsel_cost_per_charge
    hourly_labor_cost = st.session_state.hourly_labor_cost
    fern_cost_per_charge = st.session_state.fern_cost_per_charge
    fern_monthly_fixed = st.session_state.fern_monthly_fixed

    effective_hours_saved_per_charge = HOURS_PER_CHARGE_BASE * scenario_cfg["hours_multiplier"]
    total_hours_saved = charges_per_year * effective_hours_saved_per_charge

    # In-house: hours freed = cost avoided (they'd otherwise pay that salary time anyway).
    # Law firm: hours freed = billable capacity unlocked (a revenue opportunity, not a cost cut),
    # and "outside counsel avoided" doesn't apply since the firm IS outside counsel.
    hour_value = total_hours_saved * hourly_labor_cost

    effective_outside_counsel_per_charge = outside_counsel_cost_per_charge * scenario_cfg["outside_counsel_multiplier"]
    outside_counsel_savings = 0 if is_law_firm else charges_per_year * effective_outside_counsel_per_charge

    total_value_year1_full = hour_value + outside_counsel_savings

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
        "effective_hours_saved_per_charge": effective_hours_saved_per_charge,
        "total_hours_saved": total_hours_saved,
        "hour_value": hour_value,
        "effective_outside_counsel_per_charge": effective_outside_counsel_per_charge,
        "outside_counsel_savings": outside_counsel_savings,
        "total_value_year1_full": total_value_year1_full,
        "fern_annual_cost": fern_annual_cost,
        "net_value_year1_full": net_value_year1_full,
        "payback_months": max(0, payback_months),
        "money_multiple": money_multiple,
        "yearly_ramp": yearly_ramp,
        "three_year_net": three_year_net,
        "roi_3_year": max(0, roi_3_year),
    }


def build_case_study_text(is_law_firm, session_mode, scenario_cfg, roi, use_ramp):
    value_label = "Billable capacity unlocked" if is_law_firm else "Labor cost freed up"
    prepared_for = ""
    if session_mode == "Work through this with a Fern rep":
        company = f" — {st.session_state.lead_company}" if st.session_state.lead_company.strip() else ""
        prepared_for = f"Prepared for: {st.session_state.lead_name} ({st.session_state.lead_email}){company}\n"

    outside_counsel_line = "" if is_law_firm else f"Outside counsel avoided: {format_currency(roi['outside_counsel_savings'])}\n"
    law_firm_note = (
        "Note: assumes freed hours convert to billed hours at your stated rate — actual value "
        "depends on your utilization and realization rates.\n"
        if is_law_firm
        else ""
    )

    return f"""FERN LABS — PERSONALIZED ROI CASE STUDY
Generated: {date.today().strftime('%m/%d/%Y')}
Buyer type: {'Law firm / outside counsel' if is_law_firm else 'In-house legal/HR team'}
Scenario: {scenario_cfg['label']}
{prepared_for}
COMPANY PROFILE
Industry: {st.session_state.industry}
{'Attorneys/staff' if is_law_firm else 'Employee'} count: {st.session_state.employee_count:,}
Annual revenue: {format_currency(st.session_state.annual_revenue)}

USAGE ESTIMATES
Charges/matters per year: {st.session_state.charges_per_year}
{'Billable rate' if is_law_firm else 'Hourly labor cost'}: {format_currency(st.session_state.hourly_labor_cost)}
{'' if is_law_firm else f"Outside counsel cost per charge: {format_currency(st.session_state.outside_counsel_cost_per_charge)}"}

SCENARIO ADJUSTMENT
{scenario_cfg['note']}
Effective hours saved per charge: {roi['effective_hours_saved_per_charge']:.1f} (vs. {HOURS_PER_CHARGE_BASE} baseline)

ANNUAL VALUE BREAKDOWN (Year 1, full value)
------------------------------------
{value_label}: {format_currency(roi['hour_value'])}
  ({round(roi['total_hours_saved']):,} hours x {format_currency(st.session_state.hourly_labor_cost)}/hr)
{outside_counsel_line}Total gross value: {format_currency(roi['total_value_year1_full'])}
Fern Labs annual cost: {format_currency(roi['fern_annual_cost'])}
------------------------------------
NET ANNUAL VALUE (Year 1): {format_currency(roi['net_value_year1_full'])}
{law_firm_note}
KEY METRICS
------------------------------------
Return: {roi['money_multiple']:.1f}x — every $1 spent on Fern returns ~${roi['money_multiple']:.1f}
Payback period: {roi['payback_months']:.1f} months
3-year net value ({'40/70/100% adoption ramp' if use_ramp else 'full value from Year 1'}): {format_currency(roi['three_year_net'])}
3-year ROI: {roi['roi_3_year']:.1f}%

TIME SAVED
------------------------------------
Total hours freed annually: {round(roi['total_hours_saved']):,} hours
Per-charge turnaround: ~{HOURS_PER_CHARGE_BASE} hrs -> ~{HOURS_WITH_FERN_PER_CHARGE} hrs with Fern

PROOF POINT
------------------------------------
One customer's legal team went from uploading source documents to an EEOC-ready
position statement in about two hours total, versus a full day or more manually.
Fern's approach is shaped by a Customer Advisory Board of F-1000 senior employment
lawyers at companies including Tesla, Cisco, Adobe, and Walmart.

METHODOLOGY
------------------------------------
Assumptions are conservative estimates for internal discussion purposes only, developed
with input from Fern's Customer Advisory Board. Actual results vary by case complexity
and adoption speed. This is not a guarantee.

About Fern Labs
Fern Labs (Fern AI) is a purpose-built AI platform for employment law charges and
demand letters. It runs an end-to-end workflow — claim analysis, evidence extraction,
and draft generation — grounded in employment law, with every factual claim tied to a
specific exhibit so counsel can verify it. Unlimited users, no setup fee. Teams are
typically fully running within 2 weeks.

Questions? Contact sales@fernlabs.com
""".strip()


# ---- Header --------------------------------------------------------------
st.title("Fern Labs ROI calculator", text_alignment="center")
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

# ---- Company presets (in-house only) --------------------------------------
if not is_law_firm:
    with st.container(border=True):
        st.subheader("Quick-fill a company profile (optional)")
        with st.container(horizontal=True):
            for key, preset in PRESETS.items():
                st.button(preset["label"], key=f"preset_{key}", on_click=apply_preset, args=(key,))
        st.caption("Prefills industry, size, and cost assumptions — every field stays editable after.")

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
        )

        if not is_law_firm:
            st.slider(
                "Outside counsel cost per charge",
                min_value=0,
                max_value=30000,
                step=500,
                key="outside_counsel_cost_per_charge",
                format="$%d",
                help="Typical range: $10K–$20K per charge, 20–60 billed hours",
            )

        st.slider(
            "Billable rate" if is_law_firm else "Your hourly labor cost",
            min_value=0,
            max_value=1000,
            step=5,
            key="hourly_labor_cost",
            format="$%d",
            help="Rate you bill clients for this work"
            if is_law_firm
            else "Benchmark: ~$150/hr fully loaded ($300K / 2,000 hrs)",
        )

        st.markdown("**Fern Labs pricing**")
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

        st.metric(
            "Time saved annually",
            f"{round(roi['total_hours_saved']):,} hours",
            border=True,
        )
        st.caption(f"Each charge drops from ~{HOURS_PER_CHARGE_BASE} hrs to ~{HOURS_WITH_FERN_PER_CHARGE} hrs with Fern")

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

        st.download_button(
            "Get my case study" if session_mode == "Work through this with a Fern rep" else "Download case study",
            data=build_case_study_text(is_law_firm, session_mode, scenario_cfg, roi, st.session_state.use_ramp),
            file_name=f"fern-roi-case-study-{st.session_state.industry}-{'lawfirm' if is_law_firm else 'inhouse'}.txt",
            mime="text/plain",
            disabled=not can_download,
            icon=":material/download:",
            width="stretch",
            type="primary",
        )

    # ---- Savings breakdown ----
    with st.container(border=True):
        st.subheader("Annual " + ("value" if is_law_firm else "savings") + " breakdown")

        total = roi["total_value_year1_full"]

        st.write(("Billable capacity unlocked" if is_law_firm else "Labor freed up") + f" — {format_currency(roi['hour_value'])}")
        st.progress(min(1.0, roi["hour_value"] / total) if total > 0 else 0.0)

        if not is_law_firm:
            st.write(f"Outside counsel avoided — {format_currency(roi['outside_counsel_savings'])}")
            st.progress(min(1.0, roi["outside_counsel_savings"] / total) if total > 0 else 0.0)

        with st.container(horizontal=True, horizontal_alignment="distribute"):
            st.markdown("**Gross annual value**")
            st.markdown(f"**{format_currency(roi['total_value_year1_full'])}**")

        with st.container(horizontal=True, horizontal_alignment="distribute"):
            st.caption("Less: Fern Labs cost")
            st.caption(f"({format_currency(roi['fern_annual_cost'])})")

        with st.container(horizontal=True, horizontal_alignment="distribute"):
            st.markdown("**Net annual value**")
            st.markdown(f"**{format_currency(roi['net_value_year1_full'])}**")

        if st.session_state.use_ramp:
            st.markdown("**3-year adoption ramp**")
            for i, y in enumerate(roi["yearly_ramp"]):
                with st.container(horizontal=True, horizontal_alignment="distribute"):
                    st.caption(f"Year {i + 1} ({y['pct'] * 100:.0f}% adoption)")
                    st.caption(format_currency(y["net"]))

    # ---- Proof point ----
    with st.container(border=True):
        st.caption("PROOF POINT")
        st.write(
            "One customer's legal team went from uploading source documents to an EEOC-ready "
            "position statement in about two hours total — down from a full day or more done manually."
        )
        st.caption("Shaped by our Customer Advisory Board — current & former counsel at")
        with st.container(horizontal=True):
            for name in LOGOS:
                st.badge(name)

    # ---- Show the math ----
    with st.expander("Show the math", icon=":material/functions:"):
        st.code(
            f"""Hours saved = charges/year x hours saved per charge (adjusted for your current tools)
= {st.session_state.charges_per_year} x {roi['effective_hours_saved_per_charge']:.1f} hrs = {round(roi['total_hours_saved']):,} hrs

{'Billable capacity unlocked' if is_law_firm else 'Labor savings'} = hours saved x {'billable rate' if is_law_firm else 'hourly rate'}
= {round(roi['total_hours_saved']):,} x {format_currency(st.session_state.hourly_labor_cost)} = {format_currency(roi['hour_value'])}
{"" if is_law_firm else f'''
Outside counsel avoided = charges/year x cost avoided per charge
= {st.session_state.charges_per_year} x {format_currency(roi['effective_outside_counsel_per_charge'])} = {format_currency(roi['outside_counsel_savings'])}
'''}
Net value = total value - Fern annual cost
= {format_currency(roi['total_value_year1_full'])} - {format_currency(roi['fern_annual_cost'])} = {format_currency(roi['net_value_year1_full'])}""",
            language=None,
        )

# ---- Methodology / trust footer -----------------------------------------
with st.container(border=True):
    st.markdown("**Methodology**")
    st.caption(
        "These figures are conservative estimates for internal discussion purposes only, developed with input "
        "from Fern's Customer Advisory Board of F-1000 senior employment lawyers. They are not a guarantee — "
        "actual results vary by case complexity, document volume, and how quickly your team adopts the tool. "
        "Contact **sales@fernlabs.com** to build a business case specific to your caseload."
    )
