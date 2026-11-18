#!/usr/bin/env python3
"""Audit passive native state counters and apply a bank-aware IDD proxy.

The ordinary LPDDR5 background, BG-column subtraction, and refresh equations
follow DRAMPower's published LPDDR5 core calculation. PIM-local column energy
is an explicit independent parameter, NOT claimed to be calibrated by IDD.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def require(value, why):
    if not value:
        raise ValueError(why)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def audit(stats, raw):
    names = stats["command_names"]
    end = stats["elapsed_ck"]
    require(len(stats["channels"]) == 16, "missing channels")
    require(abs(end * stats["clock_ps"] / 1e6 - raw["metrics"]["total_us"]) < 1e-8, "elapsed time differs")
    totals = [Counter(), Counter()]
    command_counts = [Counter(), Counter()]
    hist_totals = [[0] * 17 for _ in range(2)]
    all_commands = 0
    fields = ("reads", "writes", "activations", "precharges", "REFpb_bank_events", "REFab_bank_events", "io_reads", "io_writes")
    for ch in stats["channels"]:
        require(ch["elapsed_ck"] == end, "channel duration differs")
        require(len(ch["banks"]) == 32, "missing bank")
        for b in ch["banks"]:
            require(sum(b["state_ck"]) == end, "bank-state duration not conserved")
        for rank in (0, 1):
            entries = [s for s in ch["stages"] if s["rank"] == rank]
            rows = [b for b in ch["banks"] if b["rank"] == rank]
            require(sum(sum(s["active_banks_ck"]) for s in entries) == end, "rank time not conserved")
            for s in entries:
                duration = sum(s["active_banks_ck"])
                require(duration == sum(s["refresh_banks_ck"]) == sum(s["active_or_refresh_banks_ck"]), "histogram time differs")
                require(sum(s["state_ck"]) == 16 * duration, "bank/stage time differs")
                weighted = lambda k: sum(i * v for i, v in enumerate(s[k]))
                require(weighted("active_banks_ck") == s["state_ck"][1] + s["state_ck"][2], "active bank-clock mismatch")
                require(weighted("refresh_banks_ck") == s["state_ck"][4], "refresh bank-clock mismatch")
                require(weighted("active_or_refresh_banks_ck") == sum(s["state_ck"][i] for i in (1, 2, 4)), "combined bank-clock mismatch")
                for f in fields:
                    totals[rank][f] += s[f]
                for n, count in zip(names, s["native_commands"]):
                    command_counts[rank][n] += count
                    all_commands += count
                for k, value in enumerate(s["active_or_refresh_banks_ck"]):
                    hist_totals[rank][k] += value
            for f in ("reads", "writes", "activations", "precharges"):
                require(sum(b[f] for b in rows) == sum(s[f] for s in entries), "bank/stage counter mismatch: " + f)
            for state in range(5):
                require(sum(b["state_ck"][state] for b in rows) == sum(s["state_ck"][state] for s in entries), "bank/state totals differ")
            require(sum(s["REFpb_bank_events"] for s in entries) == 2 * command_counts_for(entries, names, "REFpb"), "paired refresh fanout differs")
            require(sum(s["REFab_bank_events"] for s in entries) == 16 * command_counts_for(entries, names, "REFab"), "all-bank refresh fanout differs")
            primitive = sum(s["primitive_commands"][names.index("ACT2_PULSE")] for s in entries)
            single = sum(command_counts_for(entries, names, n) for n in ("ACT2", "ACT2_LOCAL"))
            require(sum(b["activations"] for b in rows) == single + primitive, "activation primitive accounting differs")
    require(all_commands == raw["metrics"]["checked_commands"], "native command count differs from original observer")
    for rank in (0, 1):
        role = "gpu" if rank == 0 else "pim"
        for direction in ("read", "write"):
            require(totals[rank]["io_" + direction + "s"] * 32 == raw["metrics"][role + "_" + direction + "_bytes"], "DQ bytes differ")
        for cmd in ("REFpb", "REFab"):
            require(command_counts[rank][cmd] == raw["refresh_commands"][f"rank{rank}"][cmd], "native refresh count differs")
    for cmd, field in (("ACT1", "GPU_act1"), ("ACT2", "GPU_act2"), ("PREpb", "GPU_prepb"), ("PREab", "GPU_preab"), ("RD", "GPU_reads"), ("WR", "GPU_writes")):
        require(command_counts[0][cmd] == raw["metrics"][field], "GPU command count differs: " + cmd)
    require(totals[0]["reads"] == raw["metrics"]["GPU_reads"] and totals[0]["writes"] == raw["metrics"]["GPU_writes"], "GPU bank column counts differ")
    return {"all_bank_and_stage_time_conserved": True, "all_histograms_reconcile": True,
            "native_command_counts_match": True, "all_DQ_bytes_match": True,
            "all_refresh_scopes_match": True, "activation_primitives_reconcile": True,
            "rank_totals": [dict(x) for x in totals],
            "rank_native_commands": [dict(x) for x in command_counts],
            "active_or_refresh_histogram_ck": hist_totals}


def command_counts_for(entries, names, name):
    idx = names.index(name)
    return sum(s["native_commands"][idx] for s in entries)


def coefficients(model, spec, rho):
    require(0 <= rho <= 1, "rho must be within [0,1]")
    v = model["voltage_V"]
    currents = model["current_mA"]
    rails = ("VDD1", "VDD2H", "VDD2L")
    p = {name: sum(v[r] * c[r] for r in rails) / 1000 for name, c in currents.items()}
    timing = spec["timings"]
    ck = spec["clock_ps"] * 1e-12
    banks = 16
    # DRAMPower LPDDR5: I_1=IDD3N, I_rho is shared rank background;
    # BG read/write characterization uses I_2, not I_1.
    shared = (banks * rho * p["IDD3N"] + (1 - rho) * p["IDD2N"]) / (banks * rho + 1 - rho)
    per_bank = p["IDD3N"] - shared
    two_bank = shared + 2 * per_bank
    full_bank = shared + banks * per_bank
    tbl = timing["nBL_min"] * ck
    trfc_pb = timing["nRFCpb"] * ck
    reference_refi_pb = timing["nREFI"] * ck / 8
    # IDD5PB is an average current; convert to its paired-bank burst
    # equivalent before subtracting the two-bank background reference.
    refpb_burst = (p["IDD5PB"] * reference_refi_pb - p["IDD2N"] * (reference_refi_pb - trfc_pb)) / trfc_pb
    q_idle = v["VDDQ"] * currents["IDD3N"]["VDDQ"] / 1000
    out = {"clock_s": ck, "precharged_W": p["IDD2N"], "shared_active_W": shared,
           "per_active_bank_W": per_bank, "two_active_banks_W": two_bank,
           "all_active_banks_W": full_bank, "VDDQ_background_W": q_idle,
           "column_read_reference_J": (p["IDD4R"] - two_bank) * tbl,
           "column_write_reference_J": (p["IDD4W"] - two_bank) * tbl,
           # This is only the combined increment. No fabricated I_beta is
           # used to claim independently measured ACT and PRE energies.
           "ACT_PRE_combined_J": (p["IDD0"] * timing["nRC"] - p["IDD3N"] * timing["nRAS"] - p["IDD2N"] * timing["nRP"]) * ck,
           "REFab_increment_W_per_refreshing_bank": (p["IDD5"] - full_bank) / banks,
           "REFpb_increment_W_per_refreshing_bank": (refpb_burst - two_bank) / 2,
           "read_DQ_J": v["VDDQ"] * (currents["IDD4R"]["VDDQ"] - currents["IDD3N"]["VDDQ"]) / 1000 * tbl,
           "write_DQ_J": v["VDDQ"] * (currents["IDD4W"]["VDDQ"] - currents["IDD3N"]["VDDQ"]) / 1000 * tbl}
    require(all(x >= 0 for x in out.values()), "negative model coefficient")
    return out


def entry_energy(s, coeff):
    c = coeff
    h = s["active_or_refresh_banks_ck"]
    rank_time = sum(h) * c["clock_s"]
    background = (h[0] * c["precharged_W"] + sum(h[k] * (c["shared_active_W"] + k * c["per_active_bank_W"]) for k in range(1, 17))) * c["clock_s"]
    return {"background_J": background + rank_time * c["VDDQ_background_W"],
            "column_read_reference_J": s["reads"] * c["column_read_reference_J"],
            "column_write_reference_J": s["writes"] * c["column_write_reference_J"],
            "DRAM_DQ_J": s["io_reads"] * c["read_DQ_J"] + s["io_writes"] * c["write_DQ_J"],
            "ACT_PRE_combined_J": s["activations"] * c["ACT_PRE_combined_J"],
            # Duration-based refresh increments clip commands still in flight
            # at the end, rather than charging beyond the measured interval.
            "refresh_increment_J": s["state_ck"][4] * c["clock_s"] * c["REFpb_increment_W_per_refreshing_bank" if s["rank"] == 0 else "REFab_increment_W_per_refreshing_bank"]}


def report(stats, raw, spec, model, rho):
    checks = audit(stats, raw)
    c = coefficients(model, spec, rho)
    ranks = [Counter(), Counter()]
    stages = {}
    for channel in stats["channels"]:
        for s in channel["stages"]:
            e = entry_energy(s, c)
            ranks[s["rank"]].update(e)
            key = s["stage_id"]
            stages.setdefault(key, Counter()).update(e)
    seconds = stats["elapsed_ck"] * c["clock_s"]
    rank_results = [{"rank": rank, "components_J": dict(r), "reference_energy_J": sum(r.values()),
                     "reference_average_power_W": sum(r.values()) / seconds} for rank, r in enumerate(ranks)]
    total = sum(sum(r.values()) for r in ranks)
    read_pim = ranks[1]["column_read_reference_J"]
    write_pim = ranks[1]["column_write_reference_J"]
    stage_info = {s["stage_id"]: s for s in raw["stages"]}
    stage_out = []
    for sid, e in sorted(stages.items()):
        info = stage_info.get(sid, {})
        stage_out.append({"stage_id": sid, "name": info.get("name", "outside_PIM_stages"),
                          "step": info.get("step"), "layer": info.get("layer"),
                          "components_J": dict(e), "reference_energy_J": sum(e.values())})
    return {"schema_version": 2, "scope": "DRAM only; exact native statistics with explicit IDD proxies",
            "statistics_validation": checks, "duration_ms": seconds * 1000,
            "reference_energy_J": total, "reference_average_power_W": total / seconds,
            "physical_power_calibrated": False,
            "PIM_energy_parameterization": {
                "definition": "P_total = fixed_W + alpha_read * PIM_read_reference_W + alpha_write * PIM_write_reference_W",
                "fixed_W": (total - read_pim - write_pim) / seconds,
                "PIM_read_reference_W": read_pim / seconds, "PIM_write_reference_W": write_pim / seconds,
                "reference_alpha_read": 1, "reference_alpha_write": 1,
                "warning": "The alpha values are not supplied or calibrated by the Micron datasheet; reference power is a modeling scenario, not a validated PIM hardware result."},
            "rho": rho, "rho_is_a_model_assumption": True, "coefficients": c,
            "ranks": rank_results, "stages": stage_out,
            "ACT_PRE_note": "Combined incremental energy, charged per actual effective activation; separate ACT/PRE energies are not claimed.",
            "part_proxy": model["source"], "excluded": model["excluded"],
            "equations_source": "https://github.com/tukl-msd/DRAMPower/blob/master/src/DRAMPower/DRAMPower/standards/lpddr5/core_calculation_LPDDR5.cpp",
            "implementation_note": "Equations aligned to upstream source; this is not a run of the upstream DRAMPower library."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stats", required=True)
    p.add_argument("--raw", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--baseline-raw")
    p.add_argument("--output", required=True)
    p.add_argument("--rho", type=float, default=0.5)
    args = p.parse_args()
    out = Path(args.output)
    require(not out.exists(), "refusing to overwrite existing report")
    files = {k: Path(getattr(args, k)) for k in ("stats", "raw", "spec", "model")}
    hashes = {str(v): sha256(v) for v in files.values()}
    data = {k: json.loads(v.read_text()) for k, v in files.items()}
    result = report(**data, rho=args.rho)
    if args.baseline_raw:
        base = Path(args.baseline_raw)
        require(sha256(base) == hashes[str(files["raw"])], "native raw differs from frozen original")
        result["statistics_validation"]["native_raw_byte_identical_to_baseline"] = True
        hashes[str(base)] = sha256(base)
    result["inputs_sha256"] = hashes
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("duration_ms", "reference_energy_J", "reference_average_power_W", "physical_power_calibrated", "PIM_energy_parameterization")}, indent=2))


if __name__ == "__main__":
    main()
