# -*- coding: utf-8 -*-
"""
Simulation LR-FHSS avec modele radio Beyrouth Rural - Bekaa Valley
(El Chall, Lahoud, El Helou - IEEE IoT Journal 2019)
+ SIC limit + gamma (modele Dumas et al.)
+ taux de succes ET goodput (bytes)
+ moyennage sur N_SEEDS seeds (avec ecart-type)
"""
from lrfhss.lrfhss_core import *
from lrfhss.acrda import BaseACRDA
from lrfhss.settings import Settings
import simpy
import numpy as np
from joblib import Parallel, delayed
from collections import defaultdict
from time import time

start_time = time()

# ============================================================
# Modele radio Beyrouth Rural - Bekaa Valley (El Chall et al., 2019)
# ============================================================
N_EXP    = 3.033
PL0      = 111.75
LH       = -6.65
H_ED     = 1.5
F_MHZ    = 868.0
P_TX_DBM = 14.0

SENSITIVITY = {
    'DR8': -138.0,
    'DR9': -137.0,
}

def path_loss(d_km, h_ed=H_ED):
    return 10 * N_EXP * np.log10(d_km) + PL0 + LH * np.log10(h_ed)

def rssi(d_km, h_ed=H_ED):
    return P_TX_DBM - path_loss(d_km, h_ed)

def is_covered(d_km, dr='DR8', h_ed=H_ED):
    return rssi(d_km, h_ed) >= SENSITIVITY[dr]

def max_distance(dr='DR8', h_ed=H_ED):
    rssi_min = SENSITIVITY[dr]
    log10_d  = (P_TX_DBM - PL0 - LH * np.log10(h_ed) - rssi_min) / (10 * N_EXP)
    return 10 ** log10_d

def packet_error_rate(d_km, dr='DR8', h_ed=H_ED):
    margin = rssi(d_km, h_ed) - SENSITIVITY[dr]
    if margin <= 0:    return 1.0
    elif margin >= 20: return 0.0
    else:              return 1 - (margin / 20)

# ============================================================
# Fragment / Packet / Node etendus avec PER radio
# ============================================================
class FragmentWithRadio(Fragment):
    def __init__(self, type, duration, channel, packet):
        super().__init__(type, duration, channel, packet)
        self.radio_lost = False

class PacketWithRadio(Packet):
    def __init__(self, node_id, obw, headers, payloads,
                 header_duration, payload_duration):
        self.id = id(self)
        self.node_id = node_id
        self.index_transmission = 0
        self.success = 0
        self.channels = random.choices(range(obw), k=headers+payloads)
        self.fragments = []
        h = 0
        for h in range(headers):
            self.fragments.append(
                FragmentWithRadio('header', header_duration,
                                  self.channels[h], self.id))
        for p in range(payloads):
            self.fragments.append(
                FragmentWithRadio('payload', payload_duration,
                                  self.channels[p+h+1], self.id))

class NodeWithRadio(Node):
    def __init__(self, obw, headers, payloads, header_duration,
                 payload_duration, transceiver_wait, traffic_generator, per):
        super().__init__(obw, headers, payloads, header_duration,
                         payload_duration, transceiver_wait, traffic_generator)
        self.per = per
        self.packet = PacketWithRadio(self.id, obw, headers, payloads,
                                      header_duration, payload_duration)

    def end_of_transmission(self):
        self.packet = PacketWithRadio(self.id, self.obw, self.headers,
                                      self.payloads, self.header_duration,
                                      self.payload_duration)

    def transmit(self, env, bs):
        while 1:
            yield env.timeout(self.next_transmission())
            self.transmitted += 1
            bs.add_packet(self.packet)
            next_fragment = self.packet.next()
            first_payload = 0
            while next_fragment:
                if first_payload == 0 and next_fragment.type == 'payload':
                    first_payload = 1
                    yield env.timeout(self.transceiver_wait)
                next_fragment.timestamp = env.now
                if random.random() < self.per:
                    yield env.timeout(next_fragment.duration)
                    next_fragment.radio_lost = True
                    next_fragment.transmitted = 1
                    next_fragment.success = 0
                else:
                    bs.check_collision(next_fragment)
                    bs.receive_packet(next_fragment)
                    yield env.timeout(next_fragment.duration)
                    bs.finish_fragment(next_fragment)
                    if self.packet.success == 0:
                        bs.try_decode(self.packet, env.now)
                next_fragment = self.packet.next()
            self.end_of_transmission()

# ============================================================
# BaseACRDA etendu : radio_lost + SIC limit + gamma
# ============================================================
class BaseACRDAWithRadio(BaseACRDA):
    def try_decode(self, packet, now):
        for f in list(packet.fragments):
            if not self.in_window(f, now):
                packet.fragments.remove(f)
            else:
                break

        def frag_ok(f):
            radio_lost = getattr(f, 'radio_lost', False)
            return (not radio_lost) and (len(f.collided) == 0) and \
                   (f.transmitted == 1) and self._is_sic_recoverable(f)

        h_success = sum(frag_ok(f) if f.type == 'header' else 0 for f in packet.fragments)
        p_success = sum(frag_ok(f) if f.type == 'payload' else 0 for f in packet.fragments)
        success = 1 if ((h_success > 0) and (p_success >= self.threshold)) else 0

        if success == 1:
            self.packets_received[packet.node_id] += 1
            packet.success = 1
            for f in packet.fragments:
                f.success = 1
                for c in list(f.collided):
                    f.collided.remove(c)
                    c.collided.remove(f)
            return True
        return False





class BaseWithRadio(Base):
    def try_decode(self, packet, now):
        def frag_ok(f):
            radio_lost = getattr(f, 'radio_lost', False)
            return (not radio_lost) and (len(f.collided) == 0) and (f.transmitted == 1)

        h_success = sum(frag_ok(f) if f.type == 'header' else 0 for f in packet.fragments)
        p_success = sum(frag_ok(f) if f.type == 'payload' else 0 for f in packet.fragments)
        success = 1 if ((h_success > 0) and (p_success >= self.threshold)) else 0

        if success == 1:
            self.packets_received[packet.node_id] += 1
            packet.success = 1
            return True
        return False





# ============================================================
# Simulation generique multi-groupes avec modele radio
# ============================================================
def run_sim_groups(groups_spec, total_nodes, distance_km,
                   dr='DR8', h_ed=H_ED, seed=0,
                   simulation_time=3600, payload_size=10,
                   code='1/3', obw=35, base='acrda',
                   sic_limit=None, gamma=1.0):

    if not is_covered(distance_km, dr, h_ed):
        return None, None

    per = packet_error_rate(distance_km, dr, h_ed)
    random.seed(seed)
    np.random.seed(seed)
    env = simpy.Environment()

    settings_list = []
    for h, prop in groups_spec:
        s = Settings(number_nodes=total_nodes, simulation_time=simulation_time,
                     payload_size=payload_size, headers=h, code=code,
                     obw=obw, base=base, sic_limit=sic_limit, gamma=gamma)
        settings_list.append((s, prop))

    avg_toa = np.mean([s.time_on_air for s, _ in settings_list])
    s0 = settings_list[0][0]

    if base == 'acrda':
        bs = BaseACRDAWithRadio(obw, s0.window_size, s0.window_step,
                            avg_toa, s0.threshold, sic_limit, gamma, seed)
        env.process(bs.sic_window(env))
    else:
        bs = BaseWithRadio(obw, s0.threshold)
    #env.process(bs.sic_window(env))

    nodes = []
    remaining = total_nodes
    for i, (s, prop) in enumerate(settings_list):
        n = int(prop * total_nodes) if i < len(settings_list) - 1 else remaining
        remaining -= n
        for _ in range(n):
            node = NodeWithRadio(s.obw, s.headers, s.payloads,
                                 s.header_duration, s.payload_duration,
                                 s.transceiver_wait, s.traffic_generator,
                                 per=per)
            bs.add_node(node.id)
            nodes.append(node)
            env.process(node.transmit(env, bs))

    env.run(until=simulation_time)

    success     = sum(bs.packets_received.values())
    transmitted = sum(n.transmitted for n in nodes)

    if transmitted == 0:
        return 1.0, 0
    return success / transmitted, success * payload_size

# ============================================================
# Job unitaire pour joblib
# ============================================================
def job(label, groups_spec, total_nodes, distance_km, seed,
        simulation_time, payload_size, code, obw, base,
        h_ed, dr, sic_limit, gamma):
    r, g = run_sim_groups(
        groups_spec=groups_spec,
        total_nodes=total_nodes,
        distance_km=distance_km,
        dr=dr,
        h_ed=h_ed,
        seed=seed,
        simulation_time=simulation_time,
        payload_size=payload_size,
        code=code,
        obw=obw,
        base=base,
        sic_limit=sic_limit,
        gamma=gamma,
    )
    return label, distance_km, sic_limit, gamma, r, g

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":

    DR              = 'DR8'
    N_NODES         = 25000 // 8
    BASE            = 'acrda'
    CODE            = '1/3'
    H_ED_M          = 1.5
    N_SEEDS         = 1
    SIMULATION_TIME = 3600
    PAYLOAD_SIZE    = 10
    OBW             = 35

    #SIC_LIMITS = [None, 2, 3, 4]
    SIC_LIMITS = [None]
    #GAMMAS     = [1.0, 0.7, 0.6, 0.5]
    GAMMAS     = [0.5]

    DISTANCES = [1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]

    DISTRIBUTIONS = [
        #('h=2 fixe',         [(2, 1.00)]),
        ('h=3 fixe',         [(3, 1.00)]),
        #('h=4 fixe',         [(4, 1.00)]),
        #('h=5 fixe',         [(5, 1.00)]),
        #('h4=0.50/h5=0.50',  [(4, 0.50), (5, 0.50)]),
        #('h4=0.75/h5=0.25',  [(4, 0.75), (5, 0.25)]),
        #('h4=0.25/h5=0.75',  [(4, 0.25), (5, 0.75)]),
        #('h2=0.50/h3=0.50',  [(2, 0.50), (3, 0.50)]),
        #('h2=0.75/h3=0.25',  [(2, 0.75), (3, 0.25)]),
        #('h2=0.25/h3=0.75',  [(2, 0.25), (3, 0.75)]),
        #('h2=h3=h4=h5=0.25', [(2, 0.25), (3, 0.25), (4, 0.25), (5, 0.25)]),
    ]

    # Info couverture
    print("=== Modele : Beyrouth Rural - Bekaa Valley (El Chall et al., 2019) ===")
    print(f"  P_tx={P_TX_DBM} dBm | n={N_EXP} | PL0={PL0} | h_ED={H_ED_M} m")
    print(f"  N_NODES={N_NODES*8} | base={BASE} | code={CODE} | seeds={N_SEEDS}")
    print()
    print("=== Distances maximales de couverture ===")
    for dr_name in SENSITIVITY:
        print(f"  {dr_name} : {max_distance(dr_name, H_ED_M):.2f} km")
    print()
    print("=== Impact hauteur end-device sur portee DR8 ===")
    for h in [0.2, 1.5, 2.0, 3.0]:
        print(f"  h_ED={h}m : {max_distance('DR8', h):.2f} km")
    print()
    print("=== Comparaison Rural vs Urbain (portee DR8, h_ED=1.5m) ===")
    print(f"  Rural  (n=3.033, PL0=111.75) : {max_distance('DR8', H_ED_M):.2f} km")
    d_urbain = 10 ** ((P_TX_DBM - 102.86 - (-6.3)*np.log10(H_ED_M) - SENSITIVITY['DR8']) / (10*4.18))
    print(f"  Urbain (n=4.18,  PL0=102.86) : {d_urbain:.2f} km")
    print()

    jobs = [
        (label, groups_spec, N_NODES, d, seed,
         SIMULATION_TIME, PAYLOAD_SIZE, CODE, OBW, BASE,
         H_ED_M, DR, sic, g)
        for label, groups_spec in DISTRIBUTIONS
        for d in DISTANCES
        for sic in SIC_LIMITS
        for g in GAMMAS
        for seed in range(N_SEEDS)
    ]

    total_jobs = len(jobs)
    print(f"Total jobs : {total_jobs}")
    print("Lancement en parallele...\n")

    results = Parallel(n_jobs=-1, verbose=0)(
        delayed(job)(*j) for j in jobs
    )

    # Agregation par (label, distance, sic_limit, gamma)
    bucket         = defaultdict(list)
    goodput_bucket = defaultdict(list)
    for label, d, sic, g, rate, gp in results:
        if rate is not None:
            bucket[(label, d, sic, g)].append(rate)
            goodput_bucket[(label, d, sic, g)].append(gp)

    # Affichage
    for sic in SIC_LIMITS:
        for g in GAMMAS:
            sic_label = str(sic) if sic is not None else 'None'
            print(f"\n{'='*70}")
            print(f"=== SIC Limit : {sic_label} | Gamma : {g} ===")
            print(f"{'='*70}")
            print(f"{'Dist (km)':<12} {'Label':<22} {'Succes moy (%)':>15} "
                  f"{'Std (%)':>8} {'Goodput moy (B)':>16} {'Std (B)':>8}")
            print("-" * 85)

            for label, _ in DISTRIBUTIONS:
                for d in DISTANCES:
                    key = (label, d, sic, g)
                    if key not in bucket:
                        print(f"{d:<12} {label:<22} hors portee")
                        continue
                    rates  = bucket[key]
                    gps    = goodput_bucket[key]
                    r_mean = np.mean(rates)
                    r_std  = np.std(rates)
                    gp_mean = np.mean(gps)
                    gp_std  = np.std(gps)
                    print(f"{d:<12} {label:<22} {r_mean*100:>15.2f} {r_std*100:>8.2f} "
                          f"{gp_mean:>16.0f} {gp_std:>8.0f}")

    elapsed = time() - start_time
    print(f"\nElapsed time: {elapsed:.2f} seconds")
