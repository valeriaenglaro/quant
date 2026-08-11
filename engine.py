##!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine.py -- unified Python pricing engine for Autocallables & Reverse
Convertibles (Yield-Enhancement), server-compatible.

>>> STRUTTURA: questo file e' la COPIA IDENTICA dei due notebook
>>> "QS Code Yield Enhancement" e "QS Code AUTOCALL" (stesso ordine, stessi
>>> nomi di variabili, stessi commenti, stesse formule), diviso per prodotto:
>>>
>>>     YIELD ENHANCEMENT                     AUTOCALL
>>>     ---------------------------------     ---------------------------------
>>>     run_monte_carlo_simulation_ye         run_monte_carlo_simulation_autocall
>>>     calculate_reverse_convertible_price   calculate_autocallable_price      (PRICING)
>>>     risk_and_analytics_ye                 risk_and_analytics_autocall       (RISK & ANALYTICS)
>>>     compute_greeks_ye                     compute_greeks_autocall           (GREEKS, bump & revalue)
>>>
>>> L'UNICA MODIFICA FUNZIONALE e' l'RNG: np.random.seed(42)+np.random.normal
>>> e' sostituito dallo stream portabile _QSRng (Lehmer LCG + Box-Muller,
>>> identico bit-a-bit a master.k). Le due righe cambiate sono marcate
>>> "<-- RNG CHANGE". Tutto il resto e' invariato.
>>>
>>> Le pochissime righe aggiunte per la compatibilita' col server (guardie
>>> anti-crash, export dei legs, lock) sono marcate "# (server)".

run(config) ritorna lo stesso JSON shape di master.k:
    {PV, Solved, solvable, legs, greeks, risk, dist}
"""

import numpy as np
import math
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq
import threading                                    # (server) run() e' serializzato

# 1. PLATFORM CONFIGURATION / 3. INPUT DATA
# (server) stessi dizionari globali dei notebook: run() li popola dal JSON,
# cosi' tutte le funzioni sotto restano IDENTICHE ai notebook (leggono i globali).

platform = {}
data = {}
coupon_config = {}
Autocall = {}
Autocall_Coupon = {}

_RUN_LOCK = threading.Lock()                        # (server) i globali non sono thread-safe


def _f(x, default=0.0):
    """Empty-safe float (mirrors the kernel's F0: '' -> 0)."""
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ============================================================================
#  QS SHARED RANDOM STREAM (portable: implemented bit-for-bit in master.k too)
#  Lehmer/Park-Miller LCG:  s_{j+1} = 48271*s_j mod (2^31-1),  seed 42.
#  Normals: Box-Muller  z = sqrt(-2 ln u1) * cos(2*pi*u2)  on consecutive
#  uniform blocks (u1 block then u2 block, per asset, row-major reshape).
#  Both engines draw THE SAME paths -> prices agree to float round-off.
# ============================================================================
# (fix) numero di colonne che l'RNG deve estrarre, indipendente da 'Days'.
# Bumpando Days cambia n_steps, quindi cambia la LUNGHEZZA dello stream e le
# path vengono ridisegnate da zero: i common random numbers saltano e theta
# diventa la differenza fra due simulazioni indipendenti invece di una derivata.
# Fissando le colonne e affettando, le path restano identiche.
_CRN_COLS = None

_QS_M = 2147483647
_QS_G = 48271
_QS_B = 65536
_QS_P = None            # g^1..g^B mod M


def _qs_powers():
    global _QS_P
    if _QS_P is None:
        p = np.empty(_QS_B, dtype=np.int64)
        v = 1
        for i in range(_QS_B):
            v = (v * _QS_G) % _QS_M
            p[i] = v
        _QS_P = p
    return _QS_P


class _QSRng:
    def __init__(self, seed=42):
        self.s = np.int64(seed)

    def uniforms(self, m):
        p = _qs_powers()
        out = np.empty(m, dtype=np.float64)
        i = 0
        s = self.s
        while i < m:
            k = min(_QS_B, m - i)
            blk = (s * p[:k]) % _QS_M          # products < 2^62: exact in int64
            out[i:i + k] = blk / float(_QS_M)
            s = blk[-1]
            i += k
        self.s = s
        return out

    def normal(self, n, d):
        m = n * d
        u1 = self.uniforms(m)
        u2 = self.uniforms(m)
        return (np.sqrt(-2.0 * np.log(u1)) * np.cos(6.283185307179586 * u2)).reshape(n, d)


# ############################################################################
# ############################################################################
# ##                                                                        ##
# ##   YIELD ENHANCEMENT / REVERSE CONVERTIBLE  (QS Code Yield Enhancement) ##
# ##                                                                        ##
# ############################################################################
# ############################################################################

# 3. MONTE CARLO SIMULATION

def run_monte_carlo_simulation_ye(n_sims=50000):

    _rng = _QSRng(42)                                          # <-- RNG CHANGE (was: np.random.seed(42))

    n_steps = int(data['Days'])
    dt = 1 / 365
    rf = data['Risk-Free Rate']

    # Storage of the pricing paths for each asset
    basket_paths = {}

    is_american = 'American' in data['Barrier Type']

    for idx in range(len(data['Underlying'])):
        asset = data['Underlying'][idx]
        vol = data['Volatility'][idx]
        beta_skew = data.get('Skew Beta', [0.15])[idx]

        pv_dividends = 0.0
        for d in data['Dividends']:
            if d['underlying_idx'] == idx:
                pv_dividends += d['amount'] * math.exp(-rf * (d['days_to_pay'] / 365))

        initial_spot = data['Spot Price'][idx]
        ref_spot = data['Spot Ref'][idx]

        # Continuous dividend yield (q): q = -ln(1 - PV_div / S_0) / T
        years = int(data['Days']) / 365.0
        q = 0.0
        if pv_dividends > 0:
            q = -math.log(1.0 - (pv_dividends / initial_spot)) / years

        # Z ~ N(0, 1)
        z_matrix = _rng.normal(n_sims, _CRN_COLS or n_steps)[:, :n_steps]   # <-- RNG CHANGE (+ fix: colonne fisse -> CRN valido anche bumpando Days) (was: np.random.normal(0.0, 1.0, size=(n_sims, n_steps)))

        if is_american:
            # --- DYNAMIC LOCAL VOLATILITY (STEP-BY-STEP) ---
            # Used for Path-Dependent options (e.g., American Daily Close)
            # Formula: Local_Vol_t = Vol_ATM + Beta * (1 - S_t / S_0)
            # Formula: S_t+1 = S_t * exp((rf - q - 0.5 * Vol_t^2) * dt + Vol_t * sqrt(dt) * Z)
            paths = np.zeros((n_sims, n_steps + 1))
            paths[:, 0] = initial_spot
            for t in range(n_steps):
                current_vol = vol + beta_skew * (1.0 - (paths[:, t] / ref_spot))   #  skew anchored to the fixing
                current_vol = np.clip(current_vol, 0.05, 1.20)
                drift = (rf - q - 0.5 * current_vol**2) * dt
                shock = current_vol * math.sqrt(dt) * z_matrix[:, t]
                paths[:, t+1] = paths[:, t] * np.exp(drift + shock)

            df_prices = pd.DataFrame(paths)
            df_prices.columns = ['Today'] + list(range(n_steps))

        else:
            # --- CONSTANT VOLATILITY (VECTORIZED) ---
            # exponent = (rf - q - 0.5 * vol^2) * dt + vol * sqrt(dt) * Z
            exponent_matrix = (rf - q - 0.5 * vol**2) * dt + (vol * math.sqrt(dt) * z_matrix)

            df = pd.DataFrame(exponent_matrix)

            # Formula: cum_exponent_t = Sum_{i=1}^{t} ( exponent_i )
            df_cum = df.cumsum(axis=1)

            # Final asset price matrix transformation
            # Formula: S_t = S_0 * exp( cum_exponent_t )
            df_prices = initial_spot * np.exp(df_cum)

            # Insert the initial spot price at the very beginning of the DataFrame (Time t=0)
            df_prices.insert(0, 'Today', initial_spot)
            df_prices.columns = ['Today'] + list(range(n_steps))

        # Store the completed asset paths DataFrame into our basket dictionary
        basket_paths[asset] = df_prices

# 4. BASKET

    # all normalizations use 'Spot Ref' (fixing) instead of 'Spot Price'.
    # The payoff is defined in % of the initial fixing

    # CASE A: Single Asset
    if len(data['Underlying']) == 1 or data['Basket Type'] == 'None':

        # Performance_t = (Spot_t / Initial_Spot) * 100
        basket_paths['Basket_Ref'] = (basket_paths[data['Underlying'][0]] / data['Spot Ref'][0]) * 100.0

    # CASE B: Multi-Asset Basket Configuration ('Worst-Of' or 'Equally Weighted')
    else:
        # Initialize a temporary list to hold the normalized 100-base performance matrices
        norm_paths = []

        # Step 1: Normalize all assets to a common percentage scale (Base 100%)
        for i in range(len(data['Underlying'])):
            name = data['Underlying'][i]

            # Perf_Matrix = (Price_Matrix / Initial_Spot) * 100
            df_norm = (basket_paths[name] / data['Spot Ref'][i]) * 100.0
            norm_paths.append(df_norm)

        # Step 2: Apply the product structural payoff rules
        if data['Basket Type'] == 'Worst-Of':

            # Financial Formula: Basket_Ref_t = min( Perf_1_t, Perf_2_t, ..., Perf_n_t ) for worst of feature
            basket_paths['Basket_Ref'] = norm_paths[0]

            for df_norm in norm_paths[1:]:
                basket_paths['Basket_Ref'] = np.minimum(basket_paths['Basket_Ref'], df_norm)

        elif data['Basket Type'] == 'Equally Weighted':

            # Basket_Ref_t = (1 / n) * Sum( Perf_i_t ) for equally weighted feature
            basket_paths['Basket_Ref'] = sum(norm_paths) / len(norm_paths)

    return basket_paths

# 5. REVERSE CONVERTIBLE PRICING

def calculate_reverse_convertible_price(basket_paths):

    n_sims = len(basket_paths[data['Underlying'][0]])
    is_eq_weighted = (data['Basket Type'] == 'Equally Weighted')

    if data['Barrier Type'] == 'American Intraday': #Broadie-Glasserman-Kou (BGK) Intraday Correction
        zeta = 0.5826 #Spitzer's constant asymptotic factor (~0.5826)
        vol = data['Volatility'][0]
        #Barrier Level Adj = Original Barrier Level  * exp(zeta * vol * sqrt(dt))
        # Shift the original lower barrier upward to penalize discrete tracking
        ki_eff = data['KI Barrier (%)'] * math.exp(zeta * vol * math.sqrt(1 / 365))
    else:
        ki_eff = data['KI Barrier (%)']

    freq_map = {'Monthly': 12, 'Quarterly': 4, 'SemiAnnually': 2, 'Yearly': 1, 'At Maturity': 1}
    freq_num = freq_map.get(coupon_config['Coupon Frequency'], coupon_config['Coupon Frequency'])

    num_payments = 1 if coupon_config['Coupon Frequency'] == 'At Maturity' else int(round((int(data['Days']) / 365.0) * freq_num))

    #At Maturity coupon
    if coupon_config['Coupon Frequency'] == 'At Maturity':
        period_cashflow = (coupon_config['Coupon (%)'] / 100.0) * (int(data['Days']) / 365.0) * data['Notional']
    else:
        period_cashflow = ((coupon_config['Coupon (%)'] / 100.0) / freq_num) * data['Notional']

    #  BOND COMPONENT

    pv_bond = data['Notional'] * math.exp(-data['Risk-Free Rate'] * (int(data['Days']) / 365))

    #  PERIODIC COUPON PAYOFF

    pv_coupons = 0.0

    if coupon_config['Coupon Type'] != 'None':

        # FIXED UNCONDITIONAL PV = Sum [ CashFlow * exp(-r * t) ] for all payment dates
        if coupon_config['Coupon Type'] == 'Fixed Unconditional':
           if coupon_config['Coupon Frequency'] == 'At Maturity':
                times = [int(data['Days']) / 365.0]
           else:
                times = np.arange(1, num_payments + 1) / freq_num #Generate exact payment fractions )

           pv_coupons = sum(
                period_cashflow * math.exp(-data['Risk-Free Rate'] * t)
                for t in times
            )

        # CONDITIONAL (WITH / WITHOUT MEMORY)
        elif 'Conditional' in coupon_config['Coupon Type']:

            # Arrays to store cashflows per path and accumulate unpaid coupons
            paths_coupons_pv = np.zeros(len(basket_paths[data['Underlying'][0]]))
            memory_stack = np.zeros(len(basket_paths[data['Underlying'][0]]))

            for i in range(1, num_payments + 1):
                day_obs = int((i / freq_num) * 365)
                col_name = min(day_obs - 1, int(data['Days']) - 1)

                # Accumulate current period coupon into the memory stack
                memory_stack += period_cashflow

                # Check if barrier is breached
                if data['Basket Type'] == 'Equally Weighted':
                    # Condition: (1/N) * Sum(S_t / S_0 * 100) >= Barrier Level %
                    avg_perf = np.zeros(len(basket_paths[data['Underlying'][0]]))

                    for idx in range(len(data['Underlying'])):
                        avg_perf += (basket_paths[data['Underlying'][idx]][col_name] / data['Spot Ref'][idx]) * 100.0

                    avg_perf /= len(data['Underlying'])
                    is_above_barrier = (avg_perf >= coupon_config['Coupon Barrier Level (%)'])

                else:
                    # Condition (Worst-Of / Single): S_i_t >= (S_i_0 * Barrier Level %) for ALL underlying assets (i)
                    is_above_barrier = np.ones(len(basket_paths[data['Underlying'][0]]), dtype=bool)

                    for idx in range(len(data['Underlying'])):
                        barrier_in_usd = data['Spot Ref'][idx] * (coupon_config['Coupon Barrier Level (%)'] / 100.0)

                        # Bitwise AND: Scenario fails if any single asset drops below its absolute barrier
                        is_above_barrier &= (basket_paths[data['Underlying'][idx]][col_name] >= barrier_in_usd)

                # Payoff & Discounting: Pay memory_stack if barrier holds, else pay 0
                paths_coupons_pv += np.where(is_above_barrier, memory_stack, 0.0) * math.exp(-data['Risk-Free Rate'] * (day_obs / 365))

                # Memory Management
                if coupon_config['Coupon Type'] == 'Conditional with Memory':
                    # Reset memory to 0 ONLY for paths that successfully received the coupon
                    memory_stack = np.where(is_above_barrier, 0.0, memory_stack)

                elif coupon_config['Coupon Type'] == 'Conditional without Memory':
                    # Clear memory completely for ALL paths, regardless of payment success
                    memory_stack = np.zeros(len(basket_paths[data['Underlying'][0]]))

            pv_coupons = np.mean(paths_coupons_pv)

    #  DOWN-AND-IN PUT OPTION PAYOFF

    pv_put_option = 0.0

    if data.get('Capital Guaranteed', 'No') != 'Yes':

        # Utilize the Basket_Ref already calculated in Step 4
        # It holds the normalized (base 100) performance according to the selected Basket Type
        ref_path = basket_paths['Basket_Ref']

        # --- DYNAMIC BARRIER CHECK ---
        if data['Barrier Type'] == 'European (Maturity)':
            is_breached = (ref_path.iloc[:, -1] <= ki_eff)   # ki_eff == input barrier here
        elif data['Barrier Type'] == 'None':
            is_breached = np.ones(n_sims, dtype=bool)
        else:
            # American Daily Close and Intraday evaluation
            is_breached = (ref_path <= ki_eff).any(axis=1)

        # --- ONE STAR FEATURE ---
        if data.get('One Star') == 'Yes':
            max_perf = np.zeros(n_sims)

            # Calculate the final performance for each asset and keep the maximum
            for idx in range(len(data['Underlying'])):
                asset = data['Underlying'][idx]
                perf = (basket_paths[asset].iloc[:, -1] / data['Spot Ref'][idx]) * 100.0
                max_perf = np.maximum(max_perf, perf)

            # Check the barrier: if max performance >= One Star Level, deactivate the breach (False)
            is_breached = np.where(max_perf >= data.get('One Star Level (%)', 100.0), False, is_breached)

        if data['Leverage (%)'] == 'Yes':
            #  1 / (Strike / 100) -> 100 / Strike_pct
            leverage_factor = 100.0 / data['Put Strike (%)']

        elif data['Leverage (%)'] == 'No':
            leverage_factor = 1.0

        else:
            leverage_factor = float(data['Leverage (%)']) / 100.0

        # Calculate the raw loss based directly on the normalized basket performance
        raw_loss_pct = np.maximum(data['Put Strike (%)'] - ref_path.iloc[:, -1], 0.0)
        max_put_loss = raw_loss_pct * (data['Notional'] / 100.0)

        conditional_put_loss = np.where(is_breached, max_put_loss, 0.0)
        array_put = conditional_put_loss * leverage_factor * math.exp(-data['Risk-Free Rate'] * (int(data['Days']) / 365))
        pv_put_option = np.mean(array_put)

    #  COMBINE COMPONENTS FOR THE FINAL PRICE

    if data.get('Capital Guaranteed', 'No') == 'Yes':
        array_put = np.zeros(n_sims)
    if 'Conditional' not in coupon_config['Coupon Type']:
        paths_coupons_pv = np.full(n_sims, pv_coupons)

    calculate_reverse_convertible_price.paths_pv = pv_bond + paths_coupons_pv - array_put
    fair_value = np.mean(calculate_reverse_convertible_price.paths_pv)

    # (server) export dei legs per il JSON di risposta (nessun impatto sul pricing)
    calculate_reverse_convertible_price.legs = {
        'bond': pv_bond, 'coupon': float(np.mean(paths_coupons_pv)),
        'autocall_coupon': 0.0, 'put': float(np.mean(array_put))}

    return fair_value


# """YE Metrics""" + """Risk Metrics"""  --  RISK & ANALYTICS (YIELD ENHANCEMENT)

def risk_and_analytics_ye(sim_output):

    ref_path = sim_output["Basket_Ref"]
    n_sims = len(ref_path)

    #  KNOCK-IN LOGIC
    # (fix) stessa barriera efficace del pricer: su Intraday il pricer applica
    # la correzione BGK, le metriche leggevano la barriera grezza.
    if data['Barrier Type'] == 'American Intraday':
        ki_barrier = data['KI Barrier (%)'] * math.exp(
            0.5826 * data['Volatility'][0] * math.sqrt(1 / 365))
    else:
        ki_barrier = data['KI Barrier (%)']

    if data['Barrier Type'] == 'None':
        is_knocked_in = (ref_path.iloc[:, -1] < data['Put Strike (%)'])


    elif 'American' in data['Barrier Type']:
        is_knocked_in = (ref_path.min(axis=1) <= ki_barrier)
    else:
        is_knocked_in = (ref_path.iloc[:, -1] <= ki_barrier)

    # (fix) ONE STAR: il pricer annulla il breach se un sottostante chiude sopra
    # il livello. Senza questo blocco le metriche descrivono un prodotto diverso
    # da quello prezzato (put dimezzato, p_capital_loss invariata).
    if data.get('One Star') == 'Yes':
        max_perf = np.zeros(n_sims)
        for idx in range(len(data['Underlying'])):
            perf = (sim_output[data['Underlying'][idx]].iloc[:, -1] / data['Spot Ref'][idx]) * 100.0
            max_perf = np.maximum(max_perf, perf)
        is_knocked_in = np.where(max_perf >= data.get('One Star Level (%)', 100.0),
                                 False, is_knocked_in)

    prob_ki = np.mean(is_knocked_in)
    prob_no_ki = np.mean(~is_knocked_in)

    # 2 Macro Scenarios Breakdown
    # 1. KI not breached (capital returned)
    prob_scenario_1 = prob_no_ki
    # 2. KI breached (capital at risk)
    prob_scenario_2 = prob_ki

    # Sanity check: the 2 scenarios must sum perfectly to 100%
    assert abs(prob_scenario_1 + prob_scenario_2 - 1.0) < 1e-9

    # """Risk Metrics"""

    final_payoffs = calculate_reverse_convertible_price.paths_pv

    # Net PnL % formula: (Final Payoff / Notional * 100) - Issue Price
    issue_price = platform.get('Issue Price (%)', 100.0)
    pnl_pct = (final_payoffs / data['Notional']) * 100.0 - issue_price

    # VALUE AT RISK (VaR)

    var_95 = np.percentile(pnl_pct, 5)

    #  EXPECTED SHORTFALL (ES / CVaR)
    # Mean of the worst-case scenarios beyond the VaR threshold: E[X | X <= VaR]
    es_95 = np.mean(pnl_pct[pnl_pct <= var_95])

    # % of paths resulting in a net loss or gain/neutral outcome
    prob_loss = np.mean(pnl_pct < 0.0) * 100
    prob_gain = np.mean(pnl_pct >= 0.0) * 100

    # (server) mappa i risultati (identici a sopra) nelle chiavi JSON del terminale
    term = ref_path.iloc[:, -1].values
    # (fix) perdita rispetto a quanto il cliente ha pagato, la stessa base che
    # usa gia' p_loss. Prima VaR/ES erano vs nozionale e p_loss vs issue price:
    # due basi diverse nello stesso blocco di output.
    loss_pct = -pnl_pct
    v95 = float(np.percentile(loss_pct, 95))
    return {"p_autocall": 0.0,
            "expected_life_y": int(data['Days']) / 365.0,
            "p_knock_in": float(prob_ki),
            "p_capital_loss": float(np.mean(is_knocked_in & (ref_path.iloc[:, -1] < data['Put Strike (%)']))),
            "exp_term_worst": float(term.mean()),
            "term_p05": float(np.percentile(term, 5)), "term_p50": float(np.percentile(term, 50)),
            "term_p95": float(np.percentile(term, 95)),
            "var95_pct": v95, "var99_pct": float(np.percentile(loss_pct, 99)),
            "es95_pct": float(loss_pct[loss_pct >= v95].mean()) if (loss_pct >= v95).any() else v95,
            "p_loss": float(prob_loss / 100.0), "p_gain": float(prob_gain / 100.0)}
            #"var_95_pnl": float(var_95), "es_95_pnl": float(es_95),
            #"prob_loss": float(prob_loss), "prob_gain": float(prob_gain),
            #"prob_no_ki": float(prob_no_ki)}


# """Greeks"""  --  (YIELD ENHANCEMENT)

# Method: bump & revalue with central finite differences.

def compute_greeks_ye(detail=1):

    N_SIMS_GREEKS = 10000
    NOTIONAL = data['Notional']

    # BUMP & REVALUE ENGINE

    def reprice(param, bump, asset_idx=None):

        # Snapshot of the only keys this function touches (list() = fresh copy)
        snap_spot = list(data['Spot Price'])
        snap_vol = list(data['Volatility'])
        snap_rate = data['Risk-Free Rate']
        snap_days = data['Days']

        try:
            if param == 'Spot':

                if asset_idx is None:
                    data['Spot Price'] = [s * (1 + bump) for s in data['Spot Price']]
                else:
                    data['Spot Price'][asset_idx] *= (1 + bump)
            elif param == 'Vol':
                data['Volatility'] = [v + bump for v in data['Volatility']]
            elif param == 'Rate':
                data['Risk-Free Rate'] += bump
            elif param == 'Days':
                data['Days'] = int(data['Days']) + bump

            # Same seed inside -> same Z draws -> same scenarios as the base run
            return calculate_reverse_convertible_price(run_monte_carlo_simulation_ye(n_sims=N_SIMS_GREEKS))
        finally:

            data['Spot Price'] = snap_spot
            data['Volatility'] = snap_vol
            data['Risk-Free Rate'] = snap_rate
            data['Days'] = snap_days

    # GREEKS CALCULATION

    # (fix) blocca la lunghezza dello stream casuale sul tenor base: cosi' il
    # bump su Days riusa le stesse path e Theta e' una vera derivata.
    global _CRN_COLS
    _CRN_COLS = int(data['Days'])

    # Base price recomputed through the same engine (zero bump)
    V0_greeks = reprice('Days', 0)

    # Sanity check
    assert abs(reprice('Days', 0) - V0_greeks) < 1e-6, "CRN Error: The Monte Carlo seed is not resetting properly."

    # Bump sizes: 1% Spot, +1 vol point (absolute), +10bp Rate (result normalized to 1bp)
    # Smaller bumps = more MC noise; larger bumps = more finite-difference bias
    h_s, h_v, h_r = 0.01, 0.01, 0.0010
    h_g = 0.05                    # (fix) bump dedicato alla Gamma, vedi sotto

    # Up/Down spot shocks computed once and reused for both Delta and Gamma
    V_S_up = reprice('Spot', h_s)
    V_S_dn = reprice('Spot', -h_s)

    # (fix) GAMMA con bump largo. La differenza seconda su un bump dell'1% vale
    # ~1e-6 del prezzo: sotto il rumore delle path che cambiano stato (autocall
    # o barriera) fra i tre repricing. Il risultato non converge e cambia segno
    # al variare del numero di path. Con bump 3/5/8% il numero e' stabile.
    # Si riscala a "per (1 punto percentuale)^2" per non cambiare la convenzione.
    V_G_up = reprice('Spot', h_g)
    V_G_dn = reprice('Spot', -h_g)
    gamma_wide = (V_G_up - 2 * V0_greeks + V_G_dn) / NOTIONAL * 100 / (h_g * 100.0) ** 2

    # Delta (per 1% move)  = [ V(S+h) - V(S-h) ] / 2
    # Gamma (per +/-1%)    = V(S+h) - 2*V(S) + V(S-h) ( NB: without dividing by h^2 this is NOT d2V/dS2, but the 2nd difference for a 1% move, i.e. "change of the 1%-Delta per 1% spot move" (desk convention).
    # Vega (per 1 vol pt)  = [ V(vol+1%) - V(vol-1%) ] / 2
    # Rho (per 1bp)        = [ V(r+10bp) - V(r-10bp) ] / (2*10)
    # Theta (per day)      = V(T-1d) - V(T)
    greeks = {
        "delta": ((V_S_up - V_S_dn) / 2) / NOTIONAL * 100,
        "gamma": gamma_wide,
        "vega": ((reprice('Vol', h_v) - reprice('Vol', -h_v)) / 2) / NOTIONAL * 100,
        "rho": ((reprice('Rate', h_r) - reprice('Rate', -h_r)) / 2 / 10) / NOTIONAL * 100,
        "theta": (reprice('Days', -1) - V0_greeks) / NOTIONAL * 100,
        "delta_per_asset": None, "vega_per_asset": None
    }

    # Hedge ratio: dV/dS = [ V(S+h) - V(S-h) ] / (2h*S) = equivalent number of shares
    delta_shares = (V_S_up - V_S_dn) / (2 * h_s * data['Spot Price'][0])
    greeks["delta_shares"] = delta_shares

    # PER-UNDERLYING DELTA (BASKETS ONLY)
    # One asset bumped at a time: the partial deltas needed to hedge asset by asset (on a Worst-Of, delta concentrates on the worst-performing underlying)

    if detail >= 2 and len(data['Underlying']) > 1:
        deltas = {}
        for i, name in enumerate(data['Underlying']):
            vu = reprice('Spot', h_s, asset_idx=i)
            vd = reprice('Spot', -h_s, asset_idx=i)
            deltas[name] = ((vu - vd) / 2) / NOTIONAL * 100

        greeks["delta_per_asset"] = [deltas[name] for name in data['Underlying']]

    _CRN_COLS = None                      # (fix) ripristina lo stream normale
    return greeks


# ############################################################################
# ############################################################################
# ##                                                                        ##
# ##   AUTOCALL  (QS Code AUTOCALL)                                         ##
# ##                                                                        ##
# ############################################################################
# ############################################################################

# 3. MONTE CARLO SIMULATION

def run_monte_carlo_simulation_autocall(n_sims=50000):
    _rng = _QSRng(42)                                          # <-- RNG CHANGE (was: np.random.seed(42))
    n_steps = int(data['Days'])
    dt = 1 / 365
    rf = data['Risk-Free Rate']

    # Storage of the pricing paths for each asset
    basket_paths = {}
    is_path_dependent = ('American' in data['Barrier Type']) or (Autocall['Type'] != 'None')

    for idx in range(len(data['Underlying'])):
        asset = data['Underlying'][idx]
        vol = data['Volatility'][idx]
        beta_skew = data.get('Skew Beta', [0.15])[idx]

        pv_dividends = 0.0
        for d in data['Dividends']:
            if d['underlying_idx'] == idx:
                pv_dividends += d['amount'] * math.exp(-rf * (d['days_to_pay'] / 365))

        initial_spot = data['Spot Price'][idx]
        ref_spot = data['Spot Ref'][idx]
        # Continuous dividend yield (q): q = -ln(1 - PV_div / S_0) / T
        years = int(data['Days']) / 365.0
        q = 0.0
        if pv_dividends > 0:
            q = -math.log(1.0 - (pv_dividends / initial_spot)) / years

        # Z ~ N(0, 1)
        z_matrix = _rng.normal(n_sims, _CRN_COLS or n_steps)[:, :n_steps]   # <-- RNG CHANGE (+ fix: colonne fisse -> CRN valido anche bumpando Days) (was: np.random.normal(0.0, 1.0, size=(n_sims, n_steps)))

        if is_path_dependent:
            # --- DYNAMIC LOCAL VOLATILITY (STEP-BY-STEP) ---
            # Used for Path-Dependent options (e.g., American Daily Close)
            # Formula: Local_Vol_t = Vol_ATM + Beta * (1 - S_t / S_0)
            # Formula: S_t+1 = S_t * exp((rf - q - 0.5 * Vol_t^2) * dt + Vol_t * sqrt(dt) * Z)
            paths = np.zeros((n_sims, n_steps + 1))
            paths[:, 0] = initial_spot
            for t in range(n_steps):
                current_vol = vol + beta_skew * (1.0 - (paths[:, t] / ref_spot))   #  skew anchored to the fixing
                current_vol = np.clip(current_vol, 0.05, 1.20)
                drift = (rf - q - 0.5 * current_vol**2) * dt
                shock = current_vol * math.sqrt(dt) * z_matrix[:, t]
                paths[:, t+1] = paths[:, t] * np.exp(drift + shock)

            df_prices = pd.DataFrame(paths)
            df_prices.columns = ['Today'] + list(range(n_steps))
        else:
            # --- CONSTANT VOLATILITY (VECTORIZED) ---
            # exponent = (rf - q - 0.5 * vol^2) * dt + vol * sqrt(dt) * Z
            exponent_matrix = (rf - q - 0.5 * vol**2) * dt + (vol * math.sqrt(dt) * z_matrix)
            df = pd.DataFrame(exponent_matrix)
            # Formula: cum_exponent_t = Sum_{i=1}^{t} ( exponent_i )
            df_cum = df.cumsum(axis=1)
            # Final asset price matrix transformation
            # Formula: S_t = S_0 * exp( cum_exponent_t )
            df_prices = initial_spot * np.exp(df_cum)
            # Insert the initial spot price at the very beginning of the DataFrame (Time t=0)
            df_prices.insert(0, 'Today', initial_spot)
            df_prices.columns = ['Today'] + list(range(n_steps))

        # Store the completed asset paths DataFrame into our basket dictionary
        basket_paths[asset] = df_prices

# 4. BASKET

    # all normalizations use 'Spot Ref' (fixing) instead of 'Spot Price'.
    # The payoff is defined in % of the initial fixing: normalizing by the same spot that

    # CASE A: Single Asset
    if len(data['Underlying']) == 1 or data['Basket Type'] == 'None':
        # Performance_t = (Spot_t / Initial_Spot) * 100
        basket_paths['Basket_Ref'] = (basket_paths[data['Underlying'][0]] / data['Spot Ref'][0]) * 100.0

    # CASE B: Multi-Asset Basket Configuration ('Worst-Of' or 'Equally Weighted')
    else:
        # Initialize a temporary list to hold the normalized 100-base performance matrices
        norm_paths = []
        # Step 1: Normalize all assets to a common percentage scale (Base 100%)
        for i in range(len(data['Underlying'])):
            name = data['Underlying'][i]
            # Perf_Matrix = (Price_Matrix / Initial_Spot) * 100
            df_norm = (basket_paths[name] / data['Spot Ref'][i]) * 100.0
            norm_paths.append(df_norm)

        # Step 2: Apply the product structural payoff rules
        if data['Basket Type'] == 'Worst-Of':
            # Financial Formula: Basket_Ref_t = min( Perf_1_t, Perf_2_t, ..., Perf_n_t ) for worst of feature
            basket_paths['Basket_Ref'] = norm_paths[0]
            for df_norm in norm_paths[1:]:
                basket_paths['Basket_Ref'] = np.minimum(basket_paths['Basket_Ref'], df_norm)
        elif data['Basket Type'] == 'Equally Weighted':
            # Basket_Ref_t = (1 / n) * Sum( Perf_i_t ) for equally weighted feature
            basket_paths['Basket_Ref'] = sum(norm_paths) / len(norm_paths)

    return basket_paths

# AUTOCALLABLE PRICING

def calculate_autocallable_price(basket_paths):
    n_sims = len(basket_paths[data['Underlying'][0]])
    is_eq_weighted = (data['Basket Type'] == 'Equally Weighted')
    n_steps = int(data['Days'])
    ref_path = basket_paths['Basket_Ref']

    if data['Barrier Type'] == 'American Intraday': #Broadie-Glasserman-Kou (BGK) Intraday Correction
        zeta = 0.5826 #Spitzer's constant asymptotic factor (~0.5826)
        vol = data['Volatility'][0]
        #Barrier Level Adj = Original Barrier Level  * exp(zeta * vol * sqrt(dt))
        # Shift the original lower barrier upward to penalize discrete tracking
        ki_eff = data['KI Barrier (%)'] * math.exp(zeta * vol * math.sqrt(1 / 365))
    else:
        ki_eff = data['KI Barrier (%)']

    freq_map = {'Monthly': 12, 'Quarterly': 4, 'SemiAnnually': 2, 'Yearly': 1, 'At Maturity': 1}
    freq_val = coupon_config.get('Coupon Frequency', 'At Maturity')
    freq_num = freq_map.get(freq_val) if freq_val in freq_map else 1
    num_payments = 1 if coupon_config['Coupon Frequency'] == 'At Maturity' else int(round((int(data['Days']) / 365.0) * freq_num))

    # At Maturity coupon
    if coupon_config['Coupon Frequency'] == 'At Maturity':
        period_cashflow = (coupon_config['Coupon (%)'] / 100.0) * (int(data['Days']) / 365.0) * data['Notional']
    else:
        period_cashflow = ((coupon_config['Coupon (%)'] / 100.0) / freq_num) * data['Notional']

    #  AUTOCALL BARRIER & AUTOCALL COUPON

    maturity_time = np.full(n_sims, float(n_steps))
    is_autocalled = np.zeros(n_sims, dtype=bool)

    #Translation of "Autocallable From" in days
    base_days_map = {'M': 30, 'Q': 90, 'S': 180, 'Y': 365}
    ac_from_str = Autocall['Autocallable From']
    unit = ac_from_str[0]
    multiplier = int(ac_from_str[1:])
    from_day = base_days_map[unit] * (multiplier - 1)

    # Array to accumulate payoffs per scenario
    paths_ac_coupon_pv = np.zeros(n_sims)

    if Autocall['Type'] != 'None':
        freq_num_ac = {'Monthly': 12, 'Quarterly': 4, 'SemiAnnually': 2, 'Yearly': 1}.get(Autocall.get('Autocall Frequency', 'Quarterly'), 4)
        total_obs = int(round((n_steps / 365.0) * freq_num_ac))
        obs_days = [int(round((i / total_obs) * n_steps)) for i in range(1, total_obs + 1)]   # (server) i/total_obs invece di i/freq_num_ac: identico per 1Y, evita l'overflow della griglia per tenor multi-anno
        obs_days = [day for day in obs_days if day >= from_day]

        for i, day in enumerate(obs_days):

            _ab = Autocall['Autocall Barrier (%)']              # (server) scalare o lista, mai crash
            if Autocall['Type'] == 'Constant Barrier':
                barrier = _ab
            elif Autocall['Type'] == 'Variable Barrier':
                barrier = (_ab[0] if isinstance(_ab, list) else _ab) + (i * Autocall['Step Up / Down (%)'])
            elif Autocall['Type'] in ['Custom Barrier', 'Custom Barrier (%)']:
                barrier = _ab[min(i, len(_ab) - 1)] if isinstance(_ab, list) else _ab
            elif Autocall['Type'] == 'Issuer Callable':
                continue

            called_today = (ref_path.iloc[:, day] >= barrier) & (~is_autocalled)
            maturity_time[called_today] = day
            is_autocalled[called_today] = True

            # --- AUTOCALL COUPON PAYOFF ---
            if Autocall_Coupon['Autocall Coupon Type'] != 'None':
                ac_coupon_pct = Autocall_Coupon['AC Coupon (%)'] / 100.0
                # Snowball (Memory) or Flat (No Memory) logic
                if Autocall_Coupon['Autocall Coupon Type'] == 'Snowball':
                    cf = (ac_coupon_pct / freq_num_ac) * (i + 1) * data['Notional']
                elif Autocall_Coupon['Autocall Coupon Type'] == 'Flat':
                    cf = ac_coupon_pct * data['Notional']
                else:
                    cf = 0.0

                # Discount and apply directly
                paths_ac_coupon_pv += np.where(called_today, cf * math.exp(-data['Risk-Free Rate'] * (day / 365.0)), 0.0)

    # Final average across all Monte Carlo scenarios
    pv_autocall_coupon = np.mean(paths_ac_coupon_pv)

    # BOND COMPONENT
    array_bond = data['Notional'] * np.exp(-data['Risk-Free Rate'] * (maturity_time / 365.0))

    #  PERIODIC COUPON PAYOFF
    pv_coupons = 0.0

    if coupon_config['Coupon Type'] != 'None':
        # FIXED UNCONDITIONAL PV = Sum [ CashFlow * exp(-r * t) ] for all payment dates
        if coupon_config['Coupon Type'] == 'Fixed Unconditional':
            if coupon_config['Coupon Frequency'] == 'At Maturity':
                paths_coupons_pv = np.where(maturity_time == n_steps, period_cashflow * math.exp(-data['Risk-Free Rate'] * (n_steps / 365.0)), 0.0)
            else:
                paths_coupons_pv = np.zeros(n_sims)
                for i in range(1, num_payments + 1):
                    day_obs = int((i / num_payments) * n_steps)   #grid scales with n_steps (identical for Days=365; needed only for Theta, where Days-1 must not drop the last coupon)
                    paid_this_period = (day_obs <= maturity_time)
                    paths_coupons_pv += np.where(paid_this_period, period_cashflow * math.exp(-data['Risk-Free Rate'] * (day_obs / 365.0)), 0.0)
            pv_coupons = np.mean(paths_coupons_pv)

        # CONDITIONAL (WITH / WITHOUT MEMORY)
        elif 'Conditional' in coupon_config['Coupon Type']:
            # Arrays to store cashflows per path and accumulate unpaid coupons
            paths_coupons_pv = np.zeros(len(basket_paths[data['Underlying'][0]]))
            memory_stack = np.zeros(len(basket_paths[data['Underlying'][0]]))

            for i in range(1, num_payments + 1):
                day_obs = int((i / num_payments) * n_steps)
                col_name = min(day_obs - 1, int(data['Days']) - 1)
                memory_stack += period_cashflow
                is_alive = (day_obs <= maturity_time)

                # Check if barrier is breached
                if data['Basket Type'] == 'Equally Weighted':
                    # Condition: (1/N) * Sum(S_t / S_0 * 100) >= Barrier Level %
                    avg_perf = np.zeros(len(basket_paths[data['Underlying'][0]]))
                    for idx in range(len(data['Underlying'])):
                        avg_perf += (basket_paths[data['Underlying'][idx]][col_name] / data['Spot Ref'][idx]) * 100.0
                    avg_perf /= len(data['Underlying'])
                    is_above_barrier = (avg_perf >= coupon_config['Coupon Barrier Level (%)'])
                else:
                    # Condition (Worst-Of / Single): S_i_t >= (S_i_0 * Barrier Level %) for ALL underlying assets (i)
                    is_above_barrier = np.ones(len(basket_paths[data['Underlying'][0]]), dtype=bool)
                    for idx in range(len(data['Underlying'])):
                        barrier_in_usd = data['Spot Ref'][idx] * (coupon_config['Coupon Barrier Level (%)'] / 100.0)
                        # Bitwise AND: Scenario fails if any single asset drops below its absolute barrier
                        is_above_barrier &= (basket_paths[data['Underlying'][idx]][col_name] >= barrier_in_usd)

                # Payoff & Discounting: Pay memory_stack if barrier holds and path is alive, else pay 0
                paths_coupons_pv += np.where(is_above_barrier & is_alive, memory_stack, 0.0) * math.exp(-data['Risk-Free Rate'] * (day_obs / 365))

                # Memory Management
                if coupon_config['Coupon Type'] == 'Conditional with Memory':
                    # Reset memory to 0 ONLY for paths that successfully received the coupon
                    memory_stack = np.where(is_above_barrier & is_alive, 0.0, memory_stack)
                elif coupon_config['Coupon Type'] == 'Conditional without Memory':
                    # Clear memory completely for ALL paths, regardless of payment success
                    memory_stack = np.zeros(len(basket_paths[data['Underlying'][0]]))

            pv_coupons = np.mean(paths_coupons_pv)

    #  DOWN-AND-IN PUT OPTION PAYOFF

    pv_put_option = 0.0
    if data.get('Capital Guaranteed', 'No') != 'Yes':
        # Utilize the Basket_Ref already calculated in Step 4
        # It holds the normalized (base 100) performance according to the selected Basket Type
        ref_path = basket_paths['Basket_Ref']

        # --- DYNAMIC BARRIER CHECK ---
        if data['Barrier Type'] == 'European (Maturity)':
            is_breached = (ref_path.iloc[:, -1] <= ki_eff)   # ki_eff == input barrier here
        elif data['Barrier Type'] == 'None':
            is_breached = np.ones(n_sims, dtype=bool)
        else:
            # American Daily Close and Intraday evaluation
            is_breached = (ref_path <= ki_eff).any(axis=1)

        # --- ONE STAR FEATURE ---
        if data.get('One Star') == 'Yes':
            max_perf = np.zeros(n_sims)
            # Calculate the final performance for each asset and keep the maximum
            for idx in range(len(data['Underlying'])):
                asset = data['Underlying'][idx]
                perf = (basket_paths[asset].iloc[:, -1] / data['Spot Ref'][idx]) * 100.0
                max_perf = np.maximum(max_perf, perf)
            # Check the barrier: if max performance >= One Star Level, deactivate the breach (False)
            is_breached = np.where(max_perf >= data.get('One Star Level (%)', 100.0), False, is_breached)

        # --- AUTOCALL PROTECTION ---
        # Paths that were autocalled cannot trigger a capital loss at maturity
        is_breached = is_breached & (~is_autocalled)

        if data['Leverage (%)'] == 'Yes':
            #  1 / (Strike / 100) -> 100 / Strike_pct
            leverage_factor = 100.0 / data['Put Strike (%)']
        elif data['Leverage (%)'] == 'No':
            leverage_factor = 1.0
        else:
            leverage_factor = float(data['Leverage (%)']) / 100.0

        # Calculate the raw loss based directly on the normalized basket performance
        raw_loss_pct = np.maximum(data['Put Strike (%)'] - ref_path.iloc[:, -1], 0.0)
        max_put_loss = raw_loss_pct * (data['Notional'] / 100.0)
        conditional_put_loss = np.where(is_breached, max_put_loss, 0.0)
        array_put = conditional_put_loss * leverage_factor * math.exp(-data['Risk-Free Rate'] * (int(data['Days']) / 365))

    #  COMBINE COMPONENTS FOR THE FINAL PRICE

    if data.get('Capital Guaranteed', 'No') == 'Yes':          # (server) guardia anti-crash: put nullo se capitale garantito
        array_put = np.zeros(n_sims)
    if coupon_config['Coupon Type'] == 'None':                 # (server) guardia anti-crash: nessuna cedola periodica
        paths_coupons_pv = np.zeros(n_sims)

    calculate_autocallable_price.paths_pv = array_bond + paths_coupons_pv + paths_ac_coupon_pv - array_put
    fair_value = np.mean(calculate_autocallable_price.paths_pv)

    # (server) export dei legs per il JSON di risposta (nessun impatto sul pricing)
    calculate_autocallable_price.legs = {
        'bond': float(np.mean(array_bond)), 'coupon': float(np.mean(paths_coupons_pv)),
        'autocall_coupon': float(pv_autocall_coupon), 'put': float(np.mean(array_put))}

    return fair_value


# """Autocall Metrics""" + """Risk Metrics"""  --  RISK & ANALYTICS (AUTOCALL)

def risk_and_analytics_autocall(sim_output):

    ref_path = sim_output["Basket_Ref"]
    n_sims = len(ref_path)

    maturity_time = np.full(n_sims, data["Days"])
    is_autocalled = np.zeros(n_sims, dtype=bool)

    autocall_probability = []
    eval_days = []

    #  AUTOCALL LOGIC
    base_days_map = {'M': 30, 'Q': 90, 'S': 180, 'Y': 365}
    if Autocall['Type'] != 'None':
        ac_from_str = Autocall['Autocallable From']
        unit = ac_from_str[0]
        multiplier = int(ac_from_str[1:])
        from_day = base_days_map[unit] * (multiplier - 1)

        freq_num_ac = {
            'Monthly': 12, 'Quarterly': 4, 'SemiAnnually': 2, 'Yearly': 1
        }.get(Autocall.get('Autocall Frequency', 'Quarterly'), 4)

        total_obs = int(round((data["Days"] / 365.0) * freq_num_ac))
        obs_days = [int(round((i / total_obs) * data["Days"])) for i in range(1, total_obs + 1)]   # (server) stessa griglia del pricing
        obs_days = [day for day in obs_days if day >= from_day]

        for i, day in enumerate(obs_days):
            _ab = Autocall['Autocall Barrier (%)']              # (server) scalare o lista, mai crash
            if Autocall['Type'] == 'Constant Barrier':
                barrier = _ab
            elif Autocall['Type'] == 'Variable Barrier':
                barrier = (_ab[0] if isinstance(_ab, list) else _ab) + (i * Autocall['Step Up / Down (%)'])
            elif Autocall['Type'] in ['Custom Barrier', 'Custom Barrier (%)']:
                barrier = _ab[min(i, len(_ab) - 1)] if isinstance(_ab, list) else _ab
            else:
                continue

            called_today = (ref_path.iloc[:, day] >= barrier) & (~is_autocalled)
            maturity_time[called_today] = day
            is_autocalled[called_today] = True

            # Marginal probability for this specific date
            autocall_probability.append(np.mean(called_today))
            eval_days.append(day)

    #  KNOCK-IN LOGIC
    # Evaluates barrier breach depending on the observation type
    # (fix) stessa barriera efficace del pricer: su Intraday il pricer applica
    # la correzione BGK, le metriche leggevano la barriera grezza.
    if data['Barrier Type'] == 'American Intraday':
        ki_barrier = data['KI Barrier (%)'] * math.exp(
            0.5826 * data['Volatility'][0] * math.sqrt(1 / 365))
    else:
        ki_barrier = data['KI Barrier (%)']
    if 'American' in data['Barrier Type']:
        is_knocked_in = (ref_path.min(axis=1) < ki_barrier)
    else:
        is_knocked_in = (ref_path.iloc[:, -1] < ki_barrier)

    # (fix) ONE STAR: il pricer annulla il breach se un sottostante chiude sopra
    # il livello. Senza questo blocco le metriche descrivono un prodotto diverso
    # da quello prezzato (put dimezzato, p_capital_loss invariata).
    if data.get('One Star') == 'Yes':
        max_perf = np.zeros(n_sims)
        for idx in range(len(data['Underlying'])):
            perf = (sim_output[data['Underlying'][idx]].iloc[:, -1] / data['Spot Ref'][idx]) * 100.0
            max_perf = np.maximum(max_perf, perf)
        is_knocked_in = np.where(max_perf >= data.get('One Star Level (%)', 100.0),
                                 False, is_knocked_in)

    #  METRICS CALCULATIONS
    prob_autocall = np.mean(is_autocalled)
    prob_maturity = np.mean(~is_autocalled)
    expected_life = np.mean(maturity_time) / 365.0

    # 3 Macro Scenarios Breakdown
    # 1. Called early (capital returned)
    prob_scenario_1 = prob_autocall
    # 2. Reaches maturity, KI not breached (capital returned)
    prob_scenario_2 = np.mean(~is_autocalled & ~is_knocked_in)
    # 3. Reaches maturity, KI breached (capital lost)
    prob_scenario_3 = np.mean(~is_autocalled & is_knocked_in)

    # Sanity check: the 3 scenarios must sum perfectly to 100%
    assert abs(prob_scenario_1 + prob_scenario_2 + prob_scenario_3 - 1.0) < 1e-9

    # """Risk Metrics"""

    final_payoffs = calculate_autocallable_price.paths_pv

    # Net PnL % formula: (Final Payoff / Notional * 100) - Issue Price
    issue_price = platform.get('Issue Price (%)', 100.0)
    pnl_pct = (final_payoffs / data['Notional']) * 100.0 - issue_price

    # VALUE AT RISK (VaR)

    var_95 = np.percentile(pnl_pct, 5)

    #  EXPECTED SHORTFALL (ES / CVaR)
    # Mean of the worst-case scenarios beyond the VaR threshold: E[X | X <= VaR]
    es_95 = np.mean(pnl_pct[pnl_pct <= var_95])

    # % of paths resulting in a net loss or gain/neutral outcome
    prob_loss = np.mean(pnl_pct < 0.0) * 100
    prob_gain = np.mean(pnl_pct >= 0.0) * 100

    # (server) mappa i risultati (identici a sopra) nelle chiavi JSON del terminale
    term = ref_path.iloc[:, -1].values
    # (fix) perdita rispetto a quanto il cliente ha pagato, la stessa base che
    # usa gia' p_loss. Prima VaR/ES erano vs nozionale e p_loss vs issue price:
    # due basi diverse nello stesso blocco di output.
    loss_pct = -pnl_pct
    v95 = float(np.percentile(loss_pct, 95))
    return {"p_autocall": float(prob_autocall),
            "expected_life_y": float(expected_life),
            "p_knock_in": float(np.mean(is_knocked_in)),
            "p_capital_loss": float(prob_scenario_3),
            "exp_term_worst": float(term.mean()),
            "term_p05": float(np.percentile(term, 5)), "term_p50": float(np.percentile(term, 50)),
            "term_p95": float(np.percentile(term, 95)),
            "var95_pct": v95, "var99_pct": float(np.percentile(loss_pct, 99)),
            "es95_pct": float(loss_pct[loss_pct >= v95].mean()) if (loss_pct >= v95).any() else v95,
            "p_loss": float(prob_loss / 100.0), "p_gain": float(prob_gain / 100.0),
            "p_maturity": float(prob_maturity),
            "autocall_probability": [float(p) for p in autocall_probability],
            "eval_days": [int(dd) for dd in eval_days]}


# """Greeks"""  --  (AUTOCALL)

# Method: bump & revalue with central finite differences.

def compute_greeks_autocall(detail=1):

    N_SIMS_GREEKS = 10000
    NOTIONAL = data['Notional']

    # BUMP & REVALUE ENGINE

    def reprice(param, bump, asset_idx=None):

        # Snapshot of the only keys this function touches (list() = fresh copy)
        snap_spot = list(data['Spot Price'])
        snap_vol = list(data['Volatility'])
        snap_rate = data['Risk-Free Rate']
        snap_days = data['Days']

        try:
            if param == 'Spot':

                if asset_idx is None:
                    data['Spot Price'] = [s * (1 + bump) for s in data['Spot Price']]
                else:
                    data['Spot Price'][asset_idx] *= (1 + bump)
            elif param == 'Vol':
                data['Volatility'] = [v + bump for v in data['Volatility']]
            elif param == 'Rate':
                data['Risk-Free Rate'] += bump
            elif param == 'Days':
                data['Days'] = int(data['Days']) + bump

            # Same seed inside -> same Z draws -> same scenarios as the base run
            return calculate_autocallable_price(run_monte_carlo_simulation_autocall(n_sims=N_SIMS_GREEKS))
        finally:

            data['Spot Price'] = snap_spot
            data['Volatility'] = snap_vol
            data['Risk-Free Rate'] = snap_rate
            data['Days'] = snap_days

    # GREEKS CALCULATION

    # (fix) blocca la lunghezza dello stream casuale sul tenor base: cosi' il
    # bump su Days riusa le stesse path e Theta e' una vera derivata.
    global _CRN_COLS
    _CRN_COLS = int(data['Days'])

    # Base price recomputed through the same engine (zero bump)
    V0_greeks = reprice('Days', 0)

    # Sanity check
    assert abs(reprice('Days', 0) - V0_greeks) < 1e-6, "CRN Error: The Monte Carlo seed is not resetting properly."

    # Bump sizes: 1% Spot, +1 vol point (absolute), +10bp Rate (result normalized to 1bp)
    # Smaller bumps = more MC noise; larger bumps = more finite-difference bias
    h_s, h_v, h_r = 0.01, 0.01, 0.0010
    h_g = 0.05                    # (fix) bump dedicato alla Gamma, vedi sotto

    # Up/Down spot shocks computed once and reused for both Delta and Gamma
    V_S_up = reprice('Spot', h_s)
    V_S_dn = reprice('Spot', -h_s)

    # (fix) GAMMA con bump largo. La differenza seconda su un bump dell'1% vale
    # ~1e-6 del prezzo: sotto il rumore delle path che cambiano stato (autocall
    # o barriera) fra i tre repricing. Il risultato non converge e cambia segno
    # al variare del numero di path. Con bump 3/5/8% il numero e' stabile.
    # Si riscala a "per (1 punto percentuale)^2" per non cambiare la convenzione.
    V_G_up = reprice('Spot', h_g)
    V_G_dn = reprice('Spot', -h_g)
    gamma_wide = (V_G_up - 2 * V0_greeks + V_G_dn) / NOTIONAL * 100 / (h_g * 100.0) ** 2

    # Delta (per 1% move)  = [ V(S+h) - V(S-h) ] / 2
    # Gamma (per +/-1%)    = V(S+h) - 2*V(S) + V(S-h) ( NB: without dividing by h^2 this is NOT d2V/dS2, but the 2nd difference for a 1% move, i.e. "change of the 1%-Delta per 1% spot move" (desk convention).
    # Vega (per 1 vol pt)  = [ V(vol+1%) - V(vol-1%) ] / 2
    # Rho (per 1bp)        = [ V(r+10bp) - V(r-10bp) ] / (2*10)
    # Theta (per day)      = V(T-1d) - V(T)
    greeks = {
        "delta": ((V_S_up - V_S_dn) / 2) / NOTIONAL * 100,
        "gamma": gamma_wide,
        "vega": ((reprice('Vol', h_v) - reprice('Vol', -h_v)) / 2) / NOTIONAL * 100,
        "rho": ((reprice('Rate', h_r) - reprice('Rate', -h_r)) / 2 / 10) / NOTIONAL * 100,
        "theta": (reprice('Days', -1) - V0_greeks) / NOTIONAL * 100,
        "delta_per_asset": None, "vega_per_asset": None
    }

    # Hedge ratio: dV/dS = [ V(S+h) - V(S-h) ] / (2h*S) = equivalent number of shares
    delta_shares = (V_S_up - V_S_dn) / (2 * h_s * data['Spot Price'][0])
    greeks["delta_shares"] = delta_shares

    # PER-UNDERLYING DELTA (BASKETS ONLY)
    # One asset bumped at a time: the partial deltas needed to hedge asset by asset (on a Worst-Of, delta concentrates on the worst-performing underlying)

    if detail >= 2 and len(data['Underlying']) > 1:
        deltas = {}
        for i, name in enumerate(data['Underlying']):
            vu = reprice('Spot', h_s, asset_idx=i)
            vd = reprice('Spot', -h_s, asset_idx=i)
            deltas[name] = ((vu - vd) / 2) / NOTIONAL * 100

        greeks["delta_per_asset"] = [deltas[name] for name in data['Underlying']]

    _CRN_COLS = None                      # (fix) ripristina lo stream normale
    return greeks


# ############################################################################
#  run(config)  --  wrapper per il server (dispatch prodotto + SOLVER dei notebook)
# ############################################################################

def _dist(sim_output, nb=40):
    """Istogramma della performance finale del basket (per il grafico 'dist')."""
    term = sim_output['Basket_Ref'].iloc[:, -1].values
    lo = float(term.min()); hi = float(term.max())
    counts, _ = np.histogram(term, bins=nb, range=(lo, hi))
    return {"lo": lo, "hi": hi, "bins": nb, "counts": counts.tolist()}


def run(config, n_sims=None):
    global platform, data, coupon_config, Autocall, Autocall_Coupon
    with _RUN_LOCK:                                            # (server) i notebook usano dizionari globali
        platform = config["platform"]
        data = config["data"]
        coupon_config = config["coupon_config"]
        Autocall = config["Autocall"]
        Autocall_Coupon = config["Autocall_Coupon"]

        # (server) sanitizzazione input dal terminale: '' -> 0, 'Spot Ref' opzionale
        data.setdefault('Spot Ref', list(data['Spot Price']))
        coupon_config['Coupon (%)'] = _f(coupon_config.get('Coupon (%)'))
        coupon_config['Coupon Barrier Level (%)'] = _f(coupon_config.get('Coupon Barrier Level (%)'))
        data['KI Barrier (%)'] = _f(data.get('KI Barrier (%)'))
        data['Put Strike (%)'] = _f(data.get('Put Strike (%)'), 100.0)
        data['One Star Level (%)'] = _f(data.get('One Star Level (%)'), 100.0)
        Autocall['Step Up / Down (%)'] = _f(Autocall.get('Step Up / Down (%)'))
        Autocall_Coupon['AC Coupon (%)'] = _f(Autocall_Coupon.get('AC Coupon (%)'))
        if not isinstance(Autocall.get('Autocall Barrier (%)'), list):
            Autocall['Autocall Barrier (%)'] = _f(Autocall.get('Autocall Barrier (%)'), 100.0)

        n_sims = int(n_sims or config.get("n_sims", 10000))
        detail = int(config.get("greeks", 1))                  # 0 nessuna | 1 basket | >=2 +per-asset

        # ---- product switch: Autocallable vs Yield-Enhancement / Rev. Convertible ----
        is_autocall_product = (Autocall.get('Type', 'None') != 'None')
        if is_autocall_product:
            run_monte_carlo_simulation = run_monte_carlo_simulation_autocall
            calculate_price = calculate_autocallable_price
            risk_and_analytics = risk_and_analytics_autocall
            compute_greeks = compute_greeks_autocall
        else:
            run_monte_carlo_simulation = run_monte_carlo_simulation_ye
            calculate_price = calculate_reverse_convertible_price
            risk_and_analytics = risk_and_analytics_ye
            compute_greeks = compute_greeks_ye

        # 6. SOLVER EXECUTION  (identico ai notebook; il margin emittente sposta il target)

        sim_output = run_monte_carlo_simulation(n_sims=n_sims)
        target_solve = platform['Solve for']
        margin = _f(platform.get('Issuer Margin (%)'))
        solvable = True

        if target_solve == 'Reoffer (%)':
            fv = calculate_price(sim_output)
            platform['Reoffer (%)'] = (fv / data['Notional']) * 100.0 + margin
            res = platform['Reoffer (%)']
        else:
            target_fv = data['Notional'] * ((_f(platform.get('Reoffer (%)'), 100.0) - margin) / 100.0)

            def objective_function(x):
                if target_solve == 'Coupon (%)':
                    coupon_config['Coupon (%)'] = x
                elif target_solve == 'KI Barrier (%)':
                    data['KI Barrier (%)'] = x
                elif target_solve == 'Coupon Barrier Level (%)':
                    coupon_config['Coupon Barrier Level (%)'] = x
                elif target_solve == 'Put Strike (%)':
                    data['Put Strike (%)'] = x
                elif target_solve == 'Autocall Coupon (%)':
                    Autocall_Coupon['AC Coupon (%)'] = x
                elif target_solve == 'Autocall Barrier (%)':
                    if isinstance(Autocall['Autocall Barrier (%)'], list):
                        Autocall['Autocall Barrier (%)'][0] = x
                    else:
                        Autocall['Autocall Barrier (%)'] = x
                return calculate_price(sim_output) - target_fv

            try:
                res = brentq(objective_function, 0.0001, 200.0)
            except ValueError:
                # (server) target non raggiungibile con questo parametro -> bound piu' vicino + flag
                solvable = False
                fl = objective_function(0.0001); fh = objective_function(200.0)
                res = 0.0001 if abs(fl) < abs(fh) else 200.0

            if target_solve == 'Coupon (%)':
                coupon_config['Coupon (%)'] = res
            elif target_solve == 'KI Barrier (%)':
                data['KI Barrier (%)'] = res
            elif target_solve == 'Coupon Barrier Level (%)':
                coupon_config['Coupon Barrier Level (%)'] = res
            elif target_solve == 'Put Strike (%)':
                data['Put Strike (%)'] = res
            elif target_solve == 'Autocall Coupon (%)':
                Autocall_Coupon['AC Coupon (%)'] = res
            elif target_solve == 'Autocall Barrier (%)':
                if isinstance(Autocall['Autocall Barrier (%)'], list):
                    Autocall['Autocall Barrier (%)'][0] = res
                else:
                    Autocall['Autocall Barrier (%)'] = res

            fv = calculate_price(sim_output)

        # ---- output JSON (stessa shape di master.k / engine precedente) ----
        NOT = data['Notional']
        legs = calculate_price.legs
        out = {"PV": (fv / NOT) * 100.0, "Solved": float(res), "solvable": solvable,
               "legs": {"bond": legs['bond'] / NOT * 100.0,
                        "coupon": legs['coupon'] / NOT * 100.0,
                        "autocall_coupon": legs['autocall_coupon'] / NOT * 100.0,
                        "put": legs['put'] / NOT * 100.0},
               "risk": risk_and_analytics(sim_output), "dist": _dist(sim_output)}

        # (server) per-date redemption split: stesse chiavi che il terminale legge da ngn/k
        _rk = out["risk"]
        if _rk.get("eval_days"):
            out["acdist"] = {"days": _rk["eval_days"],
                             "counts": [int(round(p * n_sims)) for p in _rk["autocall_probability"]],
                             "maturity_count": int(round(n_sims * (1.0 - _rk["p_autocall"])))}

        if detail >= 1:
            out["greeks"] = compute_greeks(detail)
        else:
            out["greeks"] = {"delta": None, "gamma": None, "vega": None, "rho": None,
                             "delta_per_asset": None, "vega_per_asset": None}
        return out


if __name__ == "__main__":
    import json, sys
    cfg = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "json.json"))
    print(json.dumps(run(cfg), indent=1))


# ############################################################################
# ############################################################################
# ##                                                                        ##
# ##   MARGIN  (append-only section -- nothing above this line is touched)  ##
# ##                                                                        ##
# ############################################################################
# ############################################################################
#
# Initial Margin e gestione del collaterale.
#
# CONTRATTO COL SERVER
#   server.py  ->  PYENG.compute_margin(base, cfg, cfg.get("margin", {}))
#   dove `base` e' il dict ritornato da run() (PV, greeks, risk, dist, legs).
#   Nessun global di engine.py viene letto o scritto: la sezione e' pura.
#
# UNITA' DI MISURA  (identiche a quelle prodotte da compute_greeks_*)
#   delta  : % di nozionale per 1 punto percentuale di spot
#   gamma  : % di nozionale per (1 punto percentuale)^2   [differenza seconda]
#   vega   : % di nozionale per 1 punto di volatilita'    [+0.01 assoluto]
#   rho    : % di nozionale per 1 bp di tasso
#   theta  : % di nozionale per 1 giorno di calendario
#   charge / im_pct : % di nozionale
#
# METODI
#   "1" Schedule    -- % flat sul nozionale. Fallback e floor.
#   "2" Sensitivity -- greche x moltiplicatori. Le gambe si SOMMANO: nessuna
#                      correlazione fra fattori, nessun beneficio di
#                      diversificazione. E' l'aggregazione peggior-caso, quindi
#                      non richiede di stimare una matrice di correlazione e
#                      non puo' sotto-marginare per errore di stima.
#   "3" Monte Carlo -- VaR / Expected Shortfall sull'espansione di Taylor.
#                      Spot e vol sono correlati via Cholesky con coefficiente
#                      rho_spot_vol, parametro d'ingresso dell'utente (default
#                      0.0 = indipendenti). Il tasso resta indipendente.
#                      Lo scarto fra i due metodi e'
#                      esposto in taylor_error_pct.
#
# ATTENZIONE: il metodo "2" NON e' un limite superiore del metodo "3".
# Misurato su 9.148 combinazioni casuali: mediana 1.07x, ma il metodo 2 sta
# sotto il 3 nel 41% dei casi (p05 0.43x). Due ragioni, entrambe strutturali:
#   - il VaR non e' subadditivo, quindi la somma dei quantili di gamba non
#     domina il quantile della somma;
#   - la carica gamma del metodo 2 usa 1/2*m_delta^2, cioe' il quantile di ds
#     al quadrato, mentre nella coda del P&L TOTALE lo shock che comanda e'
#     piu' estremo del quantile di ds preso da solo.
# Se serve un numero garantito conservativo, si accende use_schedule_floor
# oppure si prende il massimo fra i due metodi a valle.

MG_BUSINESS_DAYS = 252.0


# Inverse standard-normal CDF (Acklam's rational approximation, |rel err| < 1.15e-9).
# Shared verbatim with master.k so the margin z-quantile is bit-identical across
# both engines -- scipy.norm.ppf is machine-precision but not reproducible in k.
_MG_PPF_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_MG_PPF_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01)
_MG_PPF_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_MG_PPF_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
             3.754408661907416e+00)


def _mg_ppf(p):
    a, b, c, d = _MG_PPF_A, _MG_PPF_B, _MG_PPF_C, _MG_PPF_D
    if p <= 0.0:
        return -1e18
    if p >= 1.0:
        return 1e18
    if p < 0.02425:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    if p <= 0.97575:
        q = p - 0.5
        r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)


def _mg_f(x, default=0.0):
    """Float empty-safe: '' / None / non numerico -> default. Mai eccezioni."""
    if x is None or x == "":
        return default
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return default if v != v else v            # NaN -> default


def _mg_bool(x, default=False):
    if x is None:
        return default
    if isinstance(x, str):
        return x.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(x)


# =====================================================================
# 1. GRECHE DI PORTAFOGLIO
# =====================================================================
def mg_net_greeks(greeks, net_delta=True):
    """Greche nette di portafoglio, in % di nozionale.

    Unico punto in cui si leggono le greche: metodo 2, metodo 3 e stress grid
    passano di qui, quindi non possono divergere.

    delta_per_asset (basket) NON viene sommato con un beneficio di
    correlazione. Due modalita', entrambe prive di parametri stimati:
      net_delta=True  -> |somma dei delta|      (netting pieno fra sottostanti)
      net_delta=False -> somma dei |delta|      (lordo, peggior caso rho=1)
    Il segno riportato e' quello dell'esposizione netta, cosi' il termine
    gamma e il theta restano coerenti nell'espansione di Taylor.
    """
    g = greeks or {}
    per = g.get("delta_per_asset")
    if isinstance(per, (list, tuple)) and len(per) > 1:
        parts = [_mg_f(x) for x in per]
        net = sum(parts)
        gross = sum(abs(x) for x in parts)
        sign = 1.0 if net >= 0 else -1.0
        delta = net if net_delta else sign * gross
        n_factors = len(parts)
    else:
        parts = None
        delta = _mg_f(g.get("delta"))
        n_factors = 1
    return {"delta": delta,
            "gamma": _mg_f(g.get("gamma")),
            "vega": _mg_f(g.get("vega")),
            "rho": _mg_f(g.get("rho")),
            "theta": _mg_f(g.get("theta")),
            "per_asset": parts,
            "n_factors": n_factors}


# =====================================================================
# 2. MOLTIPLICATORI E DISTRIBUZIONE DEGLI SHOCK
# =====================================================================
def mg_multipliers(risk_vol, mpor_days, conf_pct, vol_of_vol=0.9,
                   rate_vol_bp=100.0, rho_spot_vol=0.0, n_sims=100000, seed=0):
    """Moltiplicatori analitici + distribuzione congiunta degli shock.

    - spot e volatilita' sono lognormali: la vol resta sempre positiva.
    - correzione di martingala -0.5*s^2 su entrambi (E[shock] = 0).
    - spot e vol sono correlati con coefficiente rho_spot_vol, imposto con la
      decomposizione di Cholesky del blocco 2x2 [[1,rho],[rho,1]], che per due
      fattori si riduce a  X1 = rho*Z0 + sqrt(1-rho^2)*Z1  (X0 = Z0).
      rho e' un input dell'utente: rho<0 riproduce lo skew azionario (spot giu'
      -> vol su'), rho=0 lascia i due fattori indipendenti.
    - il tasso resta indipendente dagli altri due.
    """
    risk_vol = max(_mg_f(risk_vol, 0.25), 1e-6)
    mpor_days = max(_mg_f(mpor_days, 10.0), 0.5)
    conf_pct = min(max(_mg_f(conf_pct, 99.0), 50.001), 99.999)
    vol_of_vol = max(_mg_f(vol_of_vol, 0.9), 0.0)
    rate_vol_bp = max(_mg_f(rate_vol_bp, 100.0), 0.0)
    rho_sv = min(max(_mg_f(rho_spot_vol, 0.0), -0.999), 0.999)
    n_sims = max(int(_mg_f(n_sims, 100000)), 2000)

    h = mpor_days / MG_BUSINESS_DAYS               # orizzonte in anni
    z = _mg_ppf(conf_pct / 100.0)                  # quantile normale (Acklam, k-portabile)
    s_spot = risk_vol * math.sqrt(h)               # dev.std log-spot
    s_vol = vol_of_vol * math.sqrt(h)              # dev.std log-vol

    # --- moltiplicatori analitici (quelli mostrati e modificabili nella UI) ---
    m_delta = (math.exp(z * s_spot - 0.5 * s_spot ** 2) - 1.0) * 100.0
    m_vega = risk_vol * (math.exp(z * s_vol - 0.5 * s_vol ** 2) - 1.0) * 100.0
    m_gamma = 0.5 * m_delta ** 2                   # coerente con 1/2 * G * ds^2
    m_rho = z * rate_vol_bp * math.sqrt(h)         # bp

    # --- distribuzione Monte Carlo -----------------------------------------
    # Cholesky sul blocco spot-vol: [[1, rho], [rho, 1]] = L L^T con
    # L = [[1, 0], [rho, sqrt(1-rho^2)]], quindi X = L Z.
    # (RNG CHANGE) stream portabile _QSRng (Lehmer LCG + Box-Muller), identico a
    # master.k: qt reset a es=42+seed, poi 3*n_sims normali flat -> Z0|Z1|Z2. Cosi'
    # il Monte Carlo del margine e' bit-identico fra engine.py e Amber.
    es = 42 + int(_mg_f(seed, 0))
    flat = _QSRng(es).normal(1, 3 * n_sims)[0]
    Z0 = flat[0:n_sims]
    Z1 = flat[n_sims:2 * n_sims]
    Z2 = flat[2 * n_sims:3 * n_sims]
    X0 = Z0
    X1 = rho_sv * Z0 + math.sqrt(1.0 - rho_sv ** 2) * Z1
    ds = (np.exp(s_spot * X0 - 0.5 * s_spot ** 2) - 1.0) * 100.0
    dv = risk_vol * (np.exp(s_vol * X1 - 0.5 * s_vol ** 2) - 1.0) * 100.0
    dr = rate_vol_bp * math.sqrt(h) * Z2

    lo, hi = 100.0 - conf_pct, conf_pct
    worst = lambda x: float(max(np.percentile(x, hi), -np.percentile(x, lo)))

    return {"ds": ds, "dv": dv, "dr": dr,
            "z": z, "m_delta": m_delta, "m_gamma": m_gamma,
            "m_vega": m_vega, "m_rho": m_rho,
            "m_delta_empirical": worst(ds), "m_vega_empirical": worst(dv),
            "sd_spot": s_spot, "sd_vol": s_vol,
            "risk_vol": risk_vol, "vol_of_vol": vol_of_vol,
            "rate_vol_bp": rate_vol_bp, "rho_spot_vol": rho_sv,
            "mpor_days": mpor_days,
            "conf_pct": conf_pct, "n_sims": n_sims, "seed": int(_mg_f(seed, 0))}


# =====================================================================
# 3. METODO 1 -- SCHEDULE (FLAT RATE)
# =====================================================================
def mg_margin_schedule(notional, rate_pct):
    """Margine flat standard sul nozionale. Usato anche come floor."""
    rate_pct = max(_mg_f(rate_pct, 8.0), 0.0)
    return {"im_pct": rate_pct,
            "im_amount": rate_pct / 100.0 * _mg_f(notional),
            "lines": [{"factor": "notional", "greek": 100.0,
                       "mult": rate_pct / 100.0, "charge": rate_pct,
                       "charged": True}]}


# =====================================================================
# 4. METODO 2 -- SENSITIVITY (GRECHE x MOLTIPLICATORI)
# =====================================================================
def mg_margin_sensitivity(gk, mult, ignore_pos_gamma=True, ignore_pos_vega=True,
                          weights=None):
    """Carica ogni greca al proprio shock e SOMMA le gambe.

    Regola di asimmetria: una greca lunga (gamma o vega positivi) puo' solo
    aiutare il cliente, quindi la sua gamba viene azzerata invece di generare
    un credito. Disattivando il flag il credito viene riconosciuto.
    Theta: si carica solo il carry negativo, mai si accredita quello positivo.
    """
    w = dict(weights or {})
    m_d = _mg_f(w.get("m_delta"), mult["m_delta"])
    m_g = _mg_f(w.get("m_gamma"), mult["m_gamma"])
    m_v = _mg_f(w.get("m_vega"), mult["m_vega"])
    m_r = _mg_f(w.get("m_rho"), mult["m_rho"])
    days = mult["mpor_days"]

    delta, gamma, vega = gk["delta"], gk["gamma"], gk["vega"]
    rho, theta = gk["rho"], gk["theta"]

    drop_g = gamma > 0.0 and ignore_pos_gamma
    drop_v = vega > 0.0 and ignore_pos_vega
    theta_charge = max(-theta * days, 0.0)

    lines = [
        {"factor": "delta", "greek": delta, "mult": m_d,
         "charge": abs(delta) * m_d, "charged": True},
        {"factor": "gamma", "greek": gamma, "mult": m_g,
         "charge": 0.0 if drop_g else -gamma * m_g, "charged": not drop_g},
        {"factor": "vega", "greek": vega, "mult": m_v,
         "charge": 0.0 if drop_v else -vega * m_v, "charged": not drop_v},
        {"factor": "rho", "greek": rho, "mult": m_r,
         "charge": abs(rho) * m_r, "charged": True},
        {"factor": "theta", "greek": theta, "mult": days,
         "charge": theta_charge, "charged": theta_charge > 0.0},
    ]
    total = sum(l["charge"] for l in lines)
    return {"im_pct": max(total, 0.0), "gross_pct": total, "lines": lines,
            "dropped": {"gamma": drop_g, "vega": drop_v}}


# =====================================================================
# 5. METODO 3 -- MONTE CARLO VaR / EXPECTED SHORTFALL + ATTRIBUTION
# =====================================================================
def mg_margin_var(gk, mult, measure="var", ignore_pos_gamma=True,
                  ignore_pos_vega=True, ignore_pos_theta=True, hist_bins=44):
    """P&L scenario per scenario con l'espansione di Taylor, poi VaR o ES.

    P&L_i = D*ds_i + 1/2*G*ds_i^2 + V*dv_i + R*dr_i + Theta*h
    La coda e' individuata sul P&L TOTALE e la stessa maschera e' applicata a
    ogni gamba: l'attribuzione di Eulero e' quindi esattamente additiva.
    """
    measure = "es" if str(measure).lower() == "es" else "var"
    ds, dv, dr = mult["ds"], mult["dv"], mult["dr"]
    delta, gamma, vega = gk["delta"], gk["gamma"], gk["vega"]
    rho, theta = gk["rho"], gk["theta"]

    # asimmetria applicata PRIMA del quantile: azzerarla dopo romperebbe
    # l'additivita' dell'attribuzione.
    drop_g = gamma > 0.0 and ignore_pos_gamma
    drop_v = vega > 0.0 and ignore_pos_vega

    pnl_delta = delta * ds
    pnl_gamma = np.zeros_like(ds) if drop_g else 0.5 * gamma * (ds ** 2)
    pnl_vega = np.zeros_like(dv) if drop_v else vega * dv
    pnl_rho = rho * dr
    # (fix) il carry sull'MPOR e' deterministico: se e' favorevole non lo si
    # accredita. Su un autocall lungo theta e' positivo (pull-to-par + rateo) e
    # senza questo floor abbassava l'IM di theta*h -- la stessa cosa che la
    # regola di asimmetria vieta per gamma e vega.
    carry = theta * mult["mpor_days"]
    if ignore_pos_theta and carry > 0.0:
        carry = 0.0
    pnl_theta = np.full_like(ds, carry)
    pnl = pnl_delta + pnl_gamma + pnl_vega + pnl_rho + pnl_theta

    conf = mult["conf_pct"]
    cut = float(np.percentile(pnl, 100.0 - conf))
    tail = pnl <= cut
    var = -cut
    es = float(-pnl[tail].mean()) if tail.any() else var

    attr = {"delta": float(-pnl_delta[tail].mean()) if tail.any() else 0.0,
            "gamma": float(-pnl_gamma[tail].mean()) if tail.any() else 0.0,
            "vega": float(-pnl_vega[tail].mean()) if tail.any() else 0.0,
            "rho": float(-pnl_rho[tail].mean()) if tail.any() else 0.0,
            "theta": float(-pnl_theta[tail].mean()) if tail.any() else 0.0}

    lo, hi = float(np.percentile(pnl, 0.2)), float(np.percentile(pnl, 99.8))
    if hi <= lo:
        hi = lo + 1.0
    counts, _ = np.histogram(pnl, bins=int(hist_bins), range=(lo, hi))

    # (fix) im_pct e' un requisito e va floorato a zero; var_pct/es_pct sono
    # misure di rischio e possono essere negative (coda in guadagno). Floorando
    # anche loro, attribution_total restava negativo mentre es_pct andava a 0 e
    # il check di additivita' di Eulero mostrava "-1.88% = 0.00%".
    return {"im_pct": max(es if measure == "es" else var, 0.0),
            "var_pct": var, "es_pct": es,
            "var95": float(-np.percentile(pnl, 5.0)),
            "var99": float(-np.percentile(pnl, 1.0)),
            "measure": measure,
            "attribution": attr,
            "attribution_total": sum(attr.values()),
            "dropped": {"gamma": drop_g, "vega": drop_v},
            "tail_scenarios": int(tail.sum()),
            "hist": {"lo": lo, "hi": hi, "bins": int(hist_bins),
                     "counts": counts.tolist(), "cut": cut}}


# =====================================================================
# 6. ANALISI DI STRESS -- GRID / HEATMAP (SPOT vs VOL)
# =====================================================================
def mg_stress_grid(gk, spot_grid_pct=None, vol_grid_pts=None, notional=None):
    """Matrice deterministica N x M di P&L. Diagnostica, non un metodo di
    margine: mostra l'economia vera, incluso il beneficio che il margine
    sceglie di non riconoscere, sugli stessi shock del Monte Carlo."""
    if not spot_grid_pct:
        spot_grid_pct = [-30.0, -20.0, -10.0, -5.0, 0.0, 5.0, 10.0, 20.0]
    if not vol_grid_pts:
        vol_grid_pts = [-10.0, -5.0, 0.0, 5.0, 10.0, 20.0]
    S, V = np.meshgrid(np.asarray(spot_grid_pct, dtype=float),
                       np.asarray(vol_grid_pts, dtype=float))
    pnl = gk["delta"] * S + 0.5 * gk["gamma"] * (S ** 2) + gk["vega"] * V
    i, j = np.unravel_index(int(np.argmin(pnl)), pnl.shape)
    out = {"spot_shocks_pct": list(spot_grid_pct),
           "vol_shocks_pts": list(vol_grid_pts),
           "pnl_grid": pnl.tolist(),
           "worst_pnl_pct": float(pnl.min()),
           "worst_scenario": {"vol_shock_pts": float(vol_grid_pts[i]),
                              "spot_shock_pct": float(spot_grid_pct[j])}}
    if notional:
        out["worst_pnl_amount"] = float(pnl.min() / 100.0 * _mg_f(notional))
    return out


# =====================================================================
# 7. COLLATERALE -- VALUTAZIONE E RETTIFICHE
# =====================================================================
def mg_collateral_line(assets, conc_pct=25.0, excess_haircut_pct=30.0):
    """Sequenza rigorosa e non commutativa: LTV -> Cap Concentrazione -> Haircut.

    Il cap si misura per EMITTENTE (campo "group", default "name"), non per
    riga: altrimenti la stessa esposizione economica spezzata su piu' righe
    risulterebbe diversificata. L'eccedenza sopra il cap non viene esclusa ma
    riceve un haircut addizionale: un pool concentrato ma di ottima qualita'
    resta utilizzabile. Cassa e governativi possono essere marcati "exempt".
    """
    assets = list(assets or [])
    total_mv = sum(_mg_f(a.get("market")) for a in assets)
    if total_mv <= 0:
        return {"rows": [], "total_market": 0.0, "cap": 0.0,
                "margin_line": 0.0, "conc_pct": _mg_f(conc_pct, 25.0)}

    cap = total_mv * max(_mg_f(conc_pct, 25.0), 0.0) / 100.0
    xh = min(max(_mg_f(excess_haircut_pct, 30.0), 0.0), 100.0) / 100.0

    # esposizione aggregata per emittente, dopo LTV e prima del cap
    grp = {}
    for a in assets:
        k = a.get("group") or a.get("name") or ""
        grp[k] = grp.get(k, 0.0) + _mg_f(a.get("market")) \
            * _mg_f(a.get("ltv_pct"), 100.0) / 100.0

    rows, eligible = [], 0.0
    for a in assets:
        mv = _mg_f(a.get("market"))
        after_ltv = mv * _mg_f(a.get("ltv_pct"), 100.0) / 100.0
        g = grp.get(a.get("group") or a.get("name") or "", 0.0)
        if _mg_bool(a.get("exempt")) or g <= cap or after_ltv <= 0 or cap <= 0:
            factor = 1.0
        else:
            factor = (cap + (g - cap) * (1.0 - xh)) / g
        after_conc = after_ltv * factor
        haircut = after_conc * _mg_f(a.get("haircut_pct")) / 100.0
        elig = after_conc - haircut
        eligible += elig
        rows.append({"name": a.get("name", ""), "ccy": a.get("ccy", ""),
                     "group": a.get("group") or a.get("name", ""),
                     "exempt": _mg_bool(a.get("exempt")),
                     "market": mv, "after_ltv": after_ltv, "factor": factor,
                     "after_conc": after_conc, "haircut": haircut,
                     "eligible": elig})
    return {"rows": rows, "total_market": total_mv, "cap": cap,
            "margin_line": float(eligible), "conc_pct": _mg_f(conc_pct, 25.0),
            "excess_haircut_pct": _mg_f(excess_haircut_pct, 30.0)}


# =====================================================================
# 8. ORCHESTRATORE CENTRALE  (entry point del server)
# =====================================================================
def compute_margin(result, cfg, params=None):
    """Orchestratore della pagina Margin.

    result : output di run() (serve greeks e, se disponibile, PV)
    cfg    : stesso config passato a run()
    params : cfg["margin"], tutto opzionale, i default sono quelli della UI
    """
    p = dict(params or {})
    result = result or {}
    data = cfg.get("data", {}) if isinstance(cfg, dict) else {}
    plat = cfg.get("platform", {}) if isinstance(cfg, dict) else {}

    notional = _mg_f(p.get("notional"), _mg_f(data.get("Notional"), 0.0))
    if notional <= 0:
        raise ValueError("Nozionale mancante o non positivo")

    # volatilita' di rischio: params vince su cfg, cosi' la pagina fa what-if
    vols = data.get("Volatility")
    cfg_vol = _mg_f(vols[0] if isinstance(vols, (list, tuple)) and vols else vols, 0.25)
    risk_vol = _mg_f(p.get("risk_vol"), cfg_vol)

    net_delta = _mg_bool(p.get("charge_abs_delta"), True)
    ig_gamma = _mg_bool(p.get("ignore_pos_gamma"), True)
    ig_vega = _mg_bool(p.get("ignore_pos_vega"), True)
    ig_theta = _mg_bool(p.get("ignore_pos_theta"), True)

    gk = mg_net_greeks(result.get("greeks") or {}, net_delta=net_delta)

    mult = mg_multipliers(risk_vol=risk_vol,
                          mpor_days=p.get("mpor_days", 10.0),
                          conf_pct=p.get("conf_pct", 99.0),
                          vol_of_vol=p.get("vol_of_vol", 0.9),
                          rate_vol_bp=p.get("rate_vol_bp", 100.0),
                          rho_spot_vol=p.get("rho_spot_vol", 0.0),
                          n_sims=p.get("n_sims", 100000),
                          seed=p.get("seed", 0))

    m1 = mg_margin_schedule(notional, p.get("schedule_rate", 8.0))
    m2 = mg_margin_sensitivity(gk, mult, ignore_pos_gamma=ig_gamma,
                               ignore_pos_vega=ig_vega,
                               weights=p.get("weights"))
    m3 = mg_margin_var(gk, mult, measure=p.get("measure", "var"),
                       ignore_pos_gamma=ig_gamma, ignore_pos_vega=ig_vega,
                       ignore_pos_theta=ig_theta)
    grid = mg_stress_grid(gk, p.get("spot_grid_pct"), p.get("vol_grid_pts"),
                          notional)

    method = str(p.get("method", "2"))
    if method not in ("1", "2", "3"):
        method = "2"
    gross = {"1": m1, "2": m2, "3": m3}[method]["im_pct"]

    # Guardia: se il pricer non ha prodotto greche (run con greeks=0, oppure
    # pricing fallito) i metodi 2 e 3 darebbero margine zero. In quel caso si
    # ricade sulla schedule: un errore a monte non puo' azzerare il requisito.
    greeks_missing = (method != "1" and
                      all(abs(gk[k]) < 1e-12 for k in ("delta", "gamma", "vega",
                                                       "rho", "theta")))
    if greeks_missing:
        gross = m1["im_pct"]

    # floor di schedule: il metodo quantitativo non puo' scendere sotto la
    # tabella se il floor e' attivo (default off, si accende dalla UI).
    floor_pct = 0.0
    if _mg_bool(p.get("use_schedule_floor"), False) and method != "1":
        floor_pct = m1["im_pct"]
        gross = max(gross, floor_pct)

    # ---- MTM: variation margin, NON un netting contro la carica di rischio --
    # Una perdita non realizzata aumenta il requisito. Un utile non realizzato
    # non riduce il rischio prospettico: viene accreditato sulla linea di
    # collaterale, e solo se il flag e' attivo.
    mtm_pct = p.get("mtm_pct")
    if mtm_pct is None:
        prev = p.get("previous_mark")
        curr = p.get("current_mark")
        if prev is not None or curr is not None:
            mtm_pct = _mg_f(curr, 100.0) - _mg_f(prev, 100.0)
        else:
            # (fix) NIENTE fallback su (PV - issue price): alla nascita il PV sta
            # sotto il prezzo di emissione per il margine d'emittente e la fee di
            # collocamento, non per una perdita di mercato. Usarlo come MTM
            # caricava variation margin sul fee gia' pagato dal cliente.
            # Il MTM va passato esplicitamente (params["mtm_pct"]) oppure dedotto
            # dai due mark; in mancanza di entrambi vale zero.
            par = p.get("par")
            pv = result.get("PV")
            mtm_pct = (_mg_f(pv) - _mg_f(par)) if (pv is not None and par) else 0.0
    mtm_pct = _mg_f(mtm_pct)
    vm_pct = -mtm_pct if mtm_pct < 0.0 else 0.0
    mtm_credit = max(mtm_pct, 0.0) if _mg_bool(p.get("use_mtm"), False) else 0.0

    im = max(gross, 0.0) + vm_pct
    mm = im * _mg_f(p.get("mm_mult"), 0.90)
    cm = im * _mg_f(p.get("cm_mult"), 0.80)

    coll = mg_collateral_line(p.get("collateral", []),
                              p.get("conc_pct", 25.0),
                              p.get("excess_haircut_pct", 30.0))
    line_pct = coll["margin_line"] / notional * 100.0 + mtm_credit

    if line_pct < cm:
        status = "liquidate"
    elif line_pct < mm:
        status = "margin_call"
    elif line_pct < im:
        status = "below_im"
    else:
        status = "hold"

    ref = m3["im_pct"] if m3["im_pct"] > 1e-9 else float("nan")
    taylor_error = (m2["im_pct"] - m3["im_pct"]) / ref * 100.0 if ref == ref else 0.0

    return {
        "method": method,
        "multipliers": {k: mult[k] for k in (
            "z", "m_delta", "m_gamma", "m_vega", "m_rho",
            "m_delta_empirical", "m_vega_empirical", "sd_spot", "sd_vol",
            "risk_vol", "vol_of_vol", "rate_vol_bp", "rho_spot_vol",
            "mpor_days", "conf_pct",
            "n_sims", "seed")},
        "greeks": {k: gk[k] for k in ("delta", "gamma", "vega", "rho",
                                      "theta", "per_asset", "n_factors")},
        "underlyings": list(data.get("Underlying") or []),
        "net_delta": net_delta,
        "methods": {"schedule": m1, "greeks": m2, "var": m3},
        "attribution": m3["attribution"],
        "stress_grid": grid,
        "gross_pct": float(gross),
        "schedule_floor_pct": float(floor_pct),
        "greeks_missing": bool(greeks_missing),
        "mtm_pct": float(mtm_pct),
        "mtm_credit_pct": float(mtm_credit),
        "variation_margin_pct": float(vm_pct),
        "variation_margin_amount": float(vm_pct / 100.0 * notional),
        "im_pct": float(im),
        "im_amount": float(im / 100.0 * notional),
        "maintenance_margin_pct": float(mm),
        "maintenance_margin_amount": float(mm / 100.0 * notional),
        "closeout_margin_pct": float(cm),
        "closeout_margin_amount": float(cm / 100.0 * notional),
        "collateral": coll,
        "margin_line_pct": float(line_pct),
        "margin_line_amount": float(line_pct / 100.0 * notional),
        "coverage_pct": float(line_pct / im * 100.0) if im > 1e-9 else None,
        "taylor_error_pct": float(taylor_error),
        "status": status,
        "notional": notional,
    }