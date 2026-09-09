"""Fuzzy-logic calculation for player suspicion."""

import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl


# FACTORY: buat simulasi fuzzy baru beserta membership function dan aturan agar state perhitungan tidak bercampur.
def _new_simulation() -> ctrl.ControlSystemSimulation:
    """Create a new simulation because its input/output state is mutable."""
    # TAHAP 4a: dua input 0..100 (agresivitas, persentase diam), satu output kecurigaan.
    aggressiveness = ctrl.Antecedent(np.arange(0, 101, 1), "aggressiveness")
    silence = ctrl.Antecedent(np.arange(0, 101, 1), "silence")
    suspicion = ctrl.Consequent(np.arange(0, 101, 1), "suspicion")

    # TAHAP 4b: membership function segitiga untuk kategori setiap variabel.
    aggressiveness["passive"] = fuzz.trimf(aggressiveness.universe, [0, 0, 40])
    aggressiveness["neutral"] = fuzz.trimf(aggressiveness.universe, [30, 50, 70])
    aggressiveness["aggressive"] = fuzz.trimf(aggressiveness.universe, [60, 100, 100])

    silence["talkative"] = fuzz.trimf(silence.universe, [0, 0, 30])
    silence["normal"] = fuzz.trimf(silence.universe, [20, 50, 80])
    silence["silent"] = fuzz.trimf(silence.universe, [70, 100, 100])

    suspicion["safe"] = fuzz.trimf(suspicion.universe, [0, 0, 40])
    suspicion["suspicious"] = fuzz.trimf(suspicion.universe, [30, 50, 70])
    suspicion["danger"] = fuzz.trimf(suspicion.universe, [60, 100, 100])

    # TAHAP 4c: aturan IF/AND/THEN yang menghubungkan kedua input dengan output.
    rules = [
        ctrl.Rule(aggressiveness["aggressive"] & silence["talkative"], suspicion["suspicious"]),
        ctrl.Rule(aggressiveness["aggressive"] & silence["normal"], suspicion["suspicious"]),
        ctrl.Rule(aggressiveness["passive"] & silence["silent"], suspicion["danger"]),
        ctrl.Rule(aggressiveness["passive"] & silence["normal"], suspicion["safe"]),
        ctrl.Rule(aggressiveness["passive"] & silence["talkative"], suspicion["safe"]),
        ctrl.Rule(aggressiveness["neutral"] & silence["normal"], suspicion["safe"]),
        ctrl.Rule(aggressiveness["neutral"] & silence["silent"], suspicion["suspicious"]),
        ctrl.Rule(aggressiveness["aggressive"] & silence["silent"], suspicion["danger"]),
        ctrl.Rule(aggressiveness["neutral"] & silence["talkative"], suspicion["safe"]),
    ]
    return ctrl.ControlSystemSimulation(ctrl.ControlSystem(rules))


# FUNCTION FUZZY: masukkan agresivitas dan persentase diam, lakukan inferensi/defuzzifikasi, lalu hasilkan skor.
def calculate_suspicion(aggressiveness_score: int, silence_percentage: int) -> float:
    simulation = _new_simulation()
    simulation.input["aggressiveness"] = aggressiveness_score
    simulation.input["silence"] = silence_percentage
    # TAHAP 4d: inferensi dan defuzzifikasi menghasilkan satu skor numerik.
    simulation.compute()
    return float(simulation.output["suspicion"])


# FUNCTION KATEGORI: petakan skor ke AMAN (<40), SUS (40 sampai <60), atau BAHAYA (>=60).
def status_for_score(score: float) -> str:
    # Label setelah perhitungan fuzzy: <40 AMAN, 40..<60 SUS, >=60 BAHAYA.
    if score >= 60:
        return "BAHAYA"
    if score >= 40:
        return "SUS"
    return "AMAN"
