'''

import random as _rnd
from lrfhss.lrfhss_core import Base

class BaseACRDA(Base):
    def __init__(self, obw, window_size, window_step, time_on_air, threshold, sic_limit=None, gamma=1.0):

        super().__init__(obw, threshold)
        self.memory = {}
        self.window_size = window_size*time_on_air
        self.window_step = window_step*time_on_air
        # sic_limit (hard model): if peak_collisions > L -> always lost.
        # gamma (probabilistic model, Dumas et al.): w_l = gamma^(l-1).
        # The two models can be combined or used independently.
        # gamma=1.0 + sic_limit=None -> original behaviour (perfect SIC).
        self.sic_limit = sic_limit
        self.gamma = gamma

    def add_packet(self, packet):
        self.memory[packet.id] = packet

    def _is_sic_recoverable(self, fragment):
        """Return True if this fragment can be recovered.

        Two independent impairment models (can be combined):

        1. Hard SIC limit (sic_limit=L):
           If peak_collisions > L the slot is declared unrecoverable
           regardless of anything else.

        2. Probabilistic model (gamma, Dumas et al. 2021):
           w_l = gamma^(l-1) is the probability of correct recovery
           when l signals were simultaneously present.
           gamma=1.0 means perfect SIC (no degradation).
        """
        l = fragment.peak_collisions  # nb of simultaneous signals (including itself)

        # Hard limit check first
        if self.sic_limit is not None and l > self.sic_limit:
            return False

        # Probabilistic check
        if self.gamma < 1.0:
            prob_success = self.gamma ** (l - 1)  # w_l = gamma^(l-1)
            return _rnd.random() < prob_success

        return True  # perfect SIC

    def try_decode(self, packet, now):
        for f in list(packet.fragments):
            if not self.in_window(f, now):
                packet.fragments.remove(f)
            else:
                break
        # A fragment counts as successfully received only if:
        #   1. No remaining collisions (collided list is empty after SIC), AND
        #   2. It was actually transmitted, AND
        #   3. Its peak simultaneous signals did not exceed the SIC limit L
        h_success = sum(
            ((len(f.collided)==0) and f.transmitted==1 and self._is_sic_recoverable(f))
            if (f.type=='header') else 0
            for f in packet.fragments
        )
        p_success = sum(
            ((len(f.collided)==0) and f.transmitted==1 and self._is_sic_recoverable(f))
            if (f.type=='payload') else 0
            for f in packet.fragments
        )
        success = 1 if ((h_success>0) and (p_success >= self.threshold)) else 0
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

    def sic_window(self, env):
        yield env.timeout(self.window_size)
        while(1):
            #FIRST: Remove fragments from memory that are outside the window.
            for p in list(self.memory):
                for f in list(self.memory[p].fragments):
                    if not self.in_window(f, env.now):
                        self.memory[p].fragments.remove(f)
                    else:
                        break
                if len(self.memory[p].fragments) == 0:
                    del(self.memory[p])
            
            #SECOND: Apply interference cancellation
            new_recover = True #variable to check if at least one packet was recovered the interference cancellation
                       #if it did, we need to do the same procedure again until no new packet is recovered
            while(new_recover):
                failed_packets = (p for p in self.memory.values() if p.success == 0)
                new_recover = False
                for p in failed_packets:
                    if self.try_decode(p,env.now):
                        new_recover = True

            yield env.timeout(self.window_step)


    def in_window(self, fragment, now):
        return True if (now - fragment.timestamp)<=self.window_size else False

        '''


'''
import random as _rnd
import numpy as _np
from lrfhss.lrfhss_core import Base

class BaseACRDA(Base):
    def __init__(self, obw, window_size, window_step, time_on_air, threshold, sic_limit=None, gamma=1.0):

        super().__init__(obw, threshold)
        self.memory = {}
        self.window_size = window_size*time_on_air
        self.window_step = window_step*time_on_air
        # sic_limit (hard model): if peak_collisions > L -> always lost.
        # gamma (probabilistic model, Dumas et al.): w_l = gamma^(l-1).
        # gamma=1.0 + sic_limit=None -> original behaviour (perfect SIC).
        self.sic_limit = sic_limit
        self.gamma = gamma
        # Generateur independant pour les decisions SIC probabilistes.
        # Ceci evite que les tirages SIC perturbent la sequence aleatoire
        # principale (trafic, canaux), garantissant que les scenarios sont
        # identiques entre differentes valeurs de gamma et que la monotonie
        # gamma=1.0 >= gamma=0.95 >= ... est toujours respectee.
        self.sic_rng = _np.random.default_rng(seed=12345)

    def add_packet(self, packet):
        self.memory[packet.id] = packet

    def _is_sic_recoverable(self, fragment):
        """Return True if this fragment can be recovered.

        Two independent impairment models (can be combined):

        1. Hard SIC limit (sic_limit=L):
           If peak_collisions > L the slot is declared unrecoverable
           regardless of anything else.

        2. Probabilistic model (gamma, Dumas et al. 2021):
           w_l = gamma^(l-1) is the probability of correct recovery
           when l signals were simultaneously present.
           gamma=1.0 means perfect SIC (no degradation).
        """
        l = fragment.peak_collisions  # nb de signaux simultanees (incluant lui-meme)

        # Hard limit check first
        if self.sic_limit is not None and l > self.sic_limit:
            return False

        # Probabilistic check — generateur independant pour ne pas perturber
        # la sequence principale (trafic, canaux)
        if self.gamma < 1.0:
            prob_success = self.gamma ** (l - 1)  # w_l = gamma^(l-1)
            return self.sic_rng.random() < prob_success  # generateur independant

        return True  # perfect SIC

    def try_decode(self, packet, now):
        for f in list(packet.fragments):
            if not self.in_window(f, now):
                packet.fragments.remove(f)
            else:
                break
        # A fragment counts as successfully received only if:
        #   1. No remaining collisions (collided list is empty after SIC), AND
        #   2. It was actually transmitted, AND
        #   3. Its peak simultaneous signals did not exceed the SIC limit L
        h_success = sum(
            ((len(f.collided)==0) and f.transmitted==1 and self._is_sic_recoverable(f))
            if (f.type=='header') else 0
            for f in packet.fragments
        )
        p_success = sum(
            ((len(f.collided)==0) and f.transmitted==1 and self._is_sic_recoverable(f))
            if (f.type=='payload') else 0
            for f in packet.fragments
        )
        success = 1 if ((h_success>0) and (p_success >= self.threshold)) else 0
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

    def sic_window(self, env):
        yield env.timeout(self.window_size)
        while(1):
            #FIRST: Remove fragments from memory that are outside the window.
            for p in list(self.memory):
                for f in list(self.memory[p].fragments):
                    if not self.in_window(f, env.now):
                        self.memory[p].fragments.remove(f)
                    else:
                        break
                if len(self.memory[p].fragments) == 0:
                    del(self.memory[p])
            
            #SECOND: Apply interference cancellation
            new_recover = True
            while(new_recover):
                failed_packets = (p for p in self.memory.values() if p.success == 0)
                new_recover = False
                for p in failed_packets:
                    if self.try_decode(p,env.now):
                        new_recover = True

            yield env.timeout(self.window_step)

    def in_window(self, fragment, now):
        return True if (now - fragment.timestamp)<=self.window_size else False
'''



'''
import random as _rnd
import numpy as _np
from lrfhss.lrfhss_core import Base

class BaseACRDA(Base):
    def __init__(self, obw, window_size, window_step, time_on_air, threshold, sic_limit=None, gamma=1.0, seed=0):

        super().__init__(obw, threshold)
        self.memory = {}
        self.window_size = window_size*time_on_air
        self.window_step = window_step*time_on_air
        # sic_limit (hard model): if peak_collisions > L -> always lost.
        # gamma (probabilistic model, Dumas et al.): w_l = gamma^(l-1).
        # gamma=1.0 + sic_limit=None -> original behaviour (perfect SIC).
        self.sic_limit = sic_limit
        self.gamma = gamma
        # Generateur independant pour les decisions SIC probabilistes.
        # Ceci evite que les tirages SIC perturbent la sequence aleatoire
        # principale (trafic, canaux), garantissant que les scenarios sont
        # identiques entre differentes valeurs de gamma et que la monotonie
        # gamma=1.0 >= gamma=0.95 >= ... est toujours respectee.
        # seed+99999 pour eviter overlap avec le generateur principal
        self.sic_rng = _np.random.default_rng(seed=seed + 99999)

    def add_packet(self, packet):
        self.memory[packet.id] = packet

    def _is_sic_recoverable(self, fragment):
        """Return True if this fragment can be recovered.

        Two independent impairment models (can be combined):

        1. Hard SIC limit (sic_limit=L):
           If peak_collisions > L the slot is declared unrecoverable
           regardless of anything else.

        2. Probabilistic model (gamma, Dumas et al. 2021):
           w_l = gamma^(l-1) is the probability of correct recovery
           when l signals were simultaneously present.
           gamma=1.0 means perfect SIC (no degradation).
        """
        l = fragment.peak_collisions  # nb de signaux simultanees (incluant lui-meme)

        # Hard limit check first
        if self.sic_limit is not None and l > self.sic_limit:
            return False

        # Probabilistic check — generateur independant pour ne pas perturber
        # la sequence principale (trafic, canaux)
        if self.gamma < 1.0:
            prob_success = self.gamma ** (l - 1)  # w_l = gamma^(l-1)
            return self.sic_rng.random() < prob_success  # generateur independant

        return True  # perfect SIC
    



    
    


















    def try_decode(self, packet, now):
        for f in list(packet.fragments):
            if not self.in_window(f, now):
                packet.fragments.remove(f)
            else:
                break
        # A fragment counts as successfully received only if:
        #   1. No remaining collisions (collided list is empty after SIC), AND
        #   2. It was actually transmitted, AND
        #   3. Its peak simultaneous signals did not exceed the SIC limit L
        h_success = sum(
            ((len(f.collided)==0) and f.transmitted==1 and self._is_sic_recoverable(f))
            if (f.type=='header') else 0
            for f in packet.fragments
        )
        p_success = sum(
            ((len(f.collided)==0) and f.transmitted==1 and self._is_sic_recoverable(f))
            if (f.type=='payload') else 0
            for f in packet.fragments
        )
        success = 1 if ((h_success>0) and (p_success >= self.threshold)) else 0
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

    def sic_window(self, env):
        yield env.timeout(self.window_size)
        while(1):
            #FIRST: Remove fragments from memory that are outside the window.
            for p in list(self.memory):
                for f in list(self.memory[p].fragments):
                    if not self.in_window(f, env.now):
                        self.memory[p].fragments.remove(f)
                    else:
                        break
                if len(self.memory[p].fragments) == 0:
                    del(self.memory[p])
            
            #SECOND: Apply interference cancellation
            new_recover = True
            while(new_recover):
                failed_packets = (p for p in self.memory.values() if p.success == 0)
                new_recover = False
                for p in failed_packets:
                    if self.try_decode(p,env.now):
                        new_recover = True
            
            yield env.timeout(self.window_step)

    def in_window(self, fragment, now):
        return True if (now - fragment.timestamp)<=self.window_size else False
'''














import random as _rnd
import numpy as _np
from lrfhss.lrfhss_core import Base

class BaseACRDA(Base):
    def __init__(self, obw, window_size, window_step, time_on_air, threshold, sic_limit=None, gamma=1.0, seed=0):

        super().__init__(obw, threshold)
        # total_collided_fragments is inherited from Base.__init__ via super().
        self.memory = {}
        self.window_size = window_size * time_on_air
        self.window_step = window_step * time_on_air
        # sic_limit (hard model): if peak_collisions > L -> always lost.
        # gamma (probabilistic model, Dumas et al.): w_l = gamma^(l-1).
        # gamma=1.0 + sic_limit=None -> original behaviour (perfect SIC).
        self.sic_limit = sic_limit
        self.gamma = gamma
        # Independent RNG for probabilistic SIC decisions.
        # Avoids perturbing the main random sequence (traffic, channels),
        # ensuring scenarios are identical across different gamma values
        # and that the monotonicity gamma=1.0 >= gamma=0.95 >= ... is preserved.
        # seed+99999 to avoid overlap with the main generator.
        self.sic_rng = _np.random.default_rng(seed=seed + 99999)


        self.headers_received = {}

    def add_packet(self, packet):
        self.memory[packet.id] = packet

    def _is_sic_recoverable(self, fragment):
        """Return True if this fragment can be recovered.

        Two independent impairment models (can be combined):

        1. Hard SIC limit (sic_limit=L):
           If peak_collisions > L the slot is declared unrecoverable
           regardless of anything else.

        2. Probabilistic model (gamma, Dumas et al. 2021):
           w_l = gamma^(l-1) is the probability of correct recovery
           when l signals were simultaneously present.
           gamma=1.0 means perfect SIC (no degradation).
        """
        l = fragment.peak_collisions  # nb of simultaneous signals (including itself)

        # Hard limit check first
        if self.sic_limit is not None and l > self.sic_limit:
            return False

        # Probabilistic check — independent RNG so it doesn't perturb
        # the main sequence (traffic, channels)
        if self.gamma < 1.0:
            prob_success = self.gamma ** (l - 1)  # w_l = gamma^(l-1)
            return self.sic_rng.random() < prob_success

        return True  # perfect SIC
    
    def try_decode(self, packet, now):
        for f in list(packet.fragments):
            if not self.in_window(f, now):
                packet.fragments.remove(f)
            else:
                break
        # A fragment counts as successfully received only if:
        #   1. No remaining collisions (collided list is empty after SIC), AND
        #   2. It was actually transmitted, AND
        #   3. Its peak simultaneous signals did not exceed the SIC limit L
        h_success = sum(
            ((len(f.collided) == 0) and f.transmitted == 1 and self._is_sic_recoverable(f))
            if (f.type == 'header') else 0
            for f in packet.fragments
        )
        p_success = sum(
            ((len(f.collided) == 0) and f.transmitted == 1 and self._is_sic_recoverable(f))
            if (f.type == 'payload') else 0
            for f in packet.fragments
        )
        # Tracker le succès header indépendamment
        if h_success > 0:
         self.headers_received[packet.node_id] = \
            self.headers_received.get(packet.node_id, 0) + 1
    
        success = 1 if ((h_success > 0) and (p_success >= self.threshold)) else 0




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

    def sic_window(self, env):
        yield env.timeout(self.window_size)
        while True:
            # FIRST: Remove fragments from memory that are outside the window.
            for p in list(self.memory):
                for f in list(self.memory[p].fragments):
                    if not self.in_window(f, env.now):
                        self.memory[p].fragments.remove(f)
                    else:
                        break
                if len(self.memory[p].fragments) == 0:
                    del self.memory[p]

            # SECOND: Apply interference cancellation.
            # Repeat until no new packet is recovered in a full pass.
            new_recover = True
            while new_recover:
                failed_packets = (p for p in self.memory.values() if p.success == 0)
                new_recover = False
                for p in failed_packets:
                    if self.try_decode(p, env.now):
                        new_recover = True

            yield env.timeout(self.window_step)

    def in_window(self, fragment, now):
        return True if (now - fragment.timestamp) <= self.window_size else False


