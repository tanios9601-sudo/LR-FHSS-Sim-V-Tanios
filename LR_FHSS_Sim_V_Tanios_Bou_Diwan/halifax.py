# -*- coding: utf-8 -*-
"""
Simulation LR-FHSS avec modèle radio Halifax
+ h=2, h=3, h=4, h=5 fixes
+ distributions mixtes h2/h3, h4/h5, h2=h3=h4=h5=0.25
+ SIC limit + gamma (modèle Dumas et al.)
+ taux de succès ET goodput (bytes)
+ moyennage sur N_SEEDS seeds (avec écart-type)
"""
from lrfhss.lrfhss_core import *
from lrfhss.acrda import BaseACRDA
from lrfhss.settings import Settings
import simpy
import numpy as np
import pandas as pd
from datetime import datetime
from time import time

start_time = time()

# ============================================================
# Modèle radio (Halifax, article Delplace et al.)
# ============================================================
A_COEFF  = 24.8065
B_COEFF  = 132.6223
P_TX_DBM = 22.0

SENSITIVITY = {
    'DR5': -138.0,
    'DR6': -137.0,
    'DR0': -120.0,
}

def path_loss(d_km):
    return A_COEFF * np.log10(d_km) + B_COEFF

def rssi(d_km):
    return P_TX_DBM - path_loss(d_km)

def is_covered(d_km, dr='DR5'):
    return rssi(d_km) >= SENSITIVITY[dr]

def max_distance(dr='DR5'):
    rssi_min = SENSITIVITY[dr]
    return 10 ** ((P_TX_DBM - B_COEFF - rssi_min) / A_COEFF)

def packet_error_rate(d_km, dr='DR5'):
    margin = rssi(d_km) - SENSITIVITY[dr]
    if margin <= 0:
        return 1.0
    elif margin >= 20:
        return 0.0
    else:
        return 1 - (margin / 20)

# ============================================================
# Fragment étendu avec flag radio_lost
# ============================================================
class FragmentWithRadio(Fragment):
    def __init__(self, type, duration, channel, packet):
        super().__init__(type, duration, channel, packet)
        self.radio_lost = False

# ============================================================
# Packet étendu qui utilise FragmentWithRadio
# ============================================================
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

# ============================================================
# Node avec prise en compte du PER radio
# ============================================================
class NodeWithRadio(Node):
    def __init__(self, obw, headers, payloads, header_duration,
                 payload_duration, transceiver_wait, traffic_generator,
                 per):
        super().__init__(obw, headers, payloads, header_duration,
                         payload_duration, transceiver_wait,
                         traffic_generator)
        self.per = per
        self.packet = PacketWithRadio(
            self.id, obw, headers, payloads,
            header_duration, payload_duration)

    def end_of_transmission(self):
        self.packet = PacketWithRadio(
            self.id, self.obw, self.headers, self.payloads,
            self.header_duration, self.payload_duration)

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
# BaseACRDA étendu qui tient compte de radio_lost
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
            # Fragment ok si : pas perdu par radio, pas de collision restante,
            # transmis, ET dans la limite SIC + gamma
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
        else:
            return False

# ============================================================
# Helpers
# ============================================================
def make_settings(n_nodes, headers, code, base, simulation_time=3600,
                  payload_size=10, obw=35, sic_limit=None, gamma=1.0):
    return Settings(
        number_nodes=n_nodes,
        simulation_time=simulation_time,
        payload_size=payload_size,
        headers=headers,
        code=code,
        obw=obw,
        base=base,
        sic_limit=sic_limit,
        gamma=gamma,
    )

def build_base(settings_list, obw, base, sic_limit=None, gamma=1.0, seed=0):
    if base == 'acrda':
        avg_toa = np.mean([s.time_on_air for s in settings_list])
        s0 = settings_list[0]
        bs = BaseACRDAWithRadio(obw, s0.window_size, s0.window_step,
                                avg_toa, s0.threshold, sic_limit, gamma, seed)
    else:
        s0 = settings_list[0]
        bs = Base(obw, s0.threshold)
    return bs

def add_nodes_from_settings(env, bs, settings, n_nodes, per):
    nodes = []
    for _ in range(n_nodes):
        node = NodeWithRadio(
            settings.obw, settings.headers, settings.payloads,
            settings.header_duration, settings.payload_duration,
            settings.transceiver_wait, settings.traffic_generator,
            per=per)
        bs.add_node(node.id)
        nodes.append(node)
        env.process(node.transmit(env, bs))
    return nodes

# ============================================================
# Simulation générique multi-groupes (une seed)
# ============================================================
def run_sim_groups(groups, total_nodes, distance_km=1.0, dr='DR5',
                   simulation_time=3600, payload_size=10, obw=35,
                   base='acrda', seed=0, sic_limit=None, gamma=1.0):
    if not is_covered(distance_km, dr):
        return None, None

    per = packet_error_rate(distance_km, dr)
    random.seed(seed)
    np.random.seed(seed)
    env = simpy.Environment()

    settings_list = [s for s, _ in groups]
    bs = build_base(settings_list, obw, base, sic_limit, gamma, seed)
    if base == 'acrda':
        env.process(bs.sic_window(env))

    all_nodes = []
    remaining = total_nodes
    for i, (s, prop) in enumerate(groups):
        n = int(prop * total_nodes) if i < len(groups) - 1 else remaining
        remaining -= n
        all_nodes += add_nodes_from_settings(env, bs, s, n, per)

    env.run(until=simulation_time)

    success     = sum(bs.packets_received.values())
    transmitted = sum(n.transmitted for n in all_nodes)

    if transmitted == 0:
        return 1.0, 0
    return success / transmitted, success * payload_size

# ============================================================
# Simulation moyennée sur plusieurs seeds
# ============================================================
def run_sim_averaged(groups, total_nodes, distance_km, dr,
                     simulation_time, payload_size, obw, base, n_seeds,
                     sic_limit=None, gamma=1.0):
    if not is_covered(distance_km, dr):
        return None, None, None, None

    rates, goodputs = [], []
    for seed in range(n_seeds):
        r, g = run_sim_groups(
            groups,
            total_nodes=total_nodes,
            distance_km=distance_km,
            dr=dr,
            simulation_time=simulation_time,
            payload_size=payload_size,
            obw=obw,
            base=base,
            seed=seed,
            sic_limit=sic_limit,
            gamma=gamma,
        )
        if r is not None:
            rates.append(r)
            goodputs.append(g)

    if not rates:
        return None, None, None, None

    return (np.mean(rates), np.std(rates),
            np.mean(goodputs), np.std(goodputs))

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":

    # =========================================================
    # Paramètres globaux
    DR              = 'DR5'
    N_NODES         = 100000 // 8
    BASE            = 'acrda'
    CODE            = '1/3'
    N_SEEDS         = 1
    SIMULATION_TIME = 3600
    PAYLOAD_SIZE    = 10
    OBW             = 35

    SIC_LIMITS = [None,2,3,4]
    #SIC_LIMITS = [None]
    GAMMAS     = [1.0,0.7,0.6,0.5]
    #GAMMAS     = [1]

    #distances = [1, 4, 6, 8, 10, 12]
    distances = [1,2,3,4,5,6,8,10,12]
    # =========================================================

    s = {
        h: make_settings(N_NODES, h, CODE, BASE, SIMULATION_TIME, PAYLOAD_SIZE, OBW)
        for h in [2, 3, 4, 5]
    }

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

    print("=== Distances maximales de couverture ===")
    for dr_name in SENSITIVITY:
        print(f"  {dr_name} : {max_distance(dr_name):.2f} km")
    print()

    rows = []

    for sic in SIC_LIMITS:
        for g in GAMMAS:
            sic_label = str(sic) if sic is not None else 'None'
            print(f"\n{'='*70}")
            print(f"=== SIC Limit : {sic_label} | Gamma : {g} ===")
            print(f"{'='*70}")
            print(f"{'Dist (km)':<12} {'Label':<22} {'Succes moy (%)':>15} {'Std (%)':>8} {'Goodput moy (B)':>16} {'Std (B)':>8}")
            print("-" * 85)

            for d in distances:
                per_val  = packet_error_rate(d, DR)
                rssi_val = rssi(d)

                if not is_covered(d, DR):
                    print(f"{d:<12} {'Hors portee':<22}")
                    continue

                for label, groups_spec in DISTRIBUTIONS:
                    groups = [(s[h], prop) for h, prop in groups_spec]

                    r_mean, r_std, gp_mean, gp_std = run_sim_averaged(
                        groups,
                        total_nodes=N_NODES,
                        distance_km=d,
                        dr=DR,
                        simulation_time=SIMULATION_TIME,
                        payload_size=PAYLOAD_SIZE,
                        obw=OBW,
                        base=BASE,
                        n_seeds=N_SEEDS,
                        sic_limit=sic,
                        gamma=g,
                    )

                    if r_mean is not None:
                        print(f"{d:<12} {label:<22} {r_mean*100:>15.2f} {r_std*100:>8.2f} {gp_mean:>16.0f} {gp_std:>8.0f}",
                              flush=True)

                        rows.append({
                            'SIC Limit'       : sic_label,
                            'Gamma'           : g,
                            'Distance (km)'   : d,
                            'RSSI (dBm)'      : round(rssi_val, 1),
                            'PER (%)'         : round(per_val * 100, 1),
                            'Distribution'    : label,
                            'Succes moy (%)'  : round(r_mean * 100, 2),
                            'Succes std (%)'  : round(r_std * 100, 2),
                            'Goodput moy (B)' : round(gp_mean),
                            'Goodput std (B)' : round(gp_std),
                        })

     #Export Excel
            #df = pd.DataFrame(rows)
            #timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            #filename  = f"resultats_halifax_sic_gamma_{timestamp}.xlsx"
            #with pd.ExcelWriter(filename, engine='openpyxl') as writer:
             #df.to_excel(writer, sheet_name='Résultats', index=False)
            #print(f"\n✅ Résultats exportés → {filename}")

    elapsed = time() - start_time
    
    print(f"\nElapsed time: {elapsed:.2f} seconds")

    #timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    #filename  = f"resultats_halifax_sic_gamma_{"halifax_h2=h3_150k"}.xlsx"
    #df = pd.DataFrame(rows)
    
    #with pd.ExcelWriter(filename, engine='openpyxl') as writer:
    #    for g in GAMMAS:
    #        df_g = df[df['Gamma'] == g]
    #        sheet_name = f"gamma={g}"
    #        df_g.to_excel(writer, sheet_name=sheet_name, index=False)
    
    #print(f"\n✅ Résultats exportés → {filename}")
   