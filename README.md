# LR-FHSS-Sim-V-Tanios

Adapted version of the original LR-FHSS-Sim simulator, extended to study the impact of limited and imperfect Successive Interference Cancellation (SIC) on LR-FHSS reliability and to incorporate radio propagation models for more realistic network simulations.

## Overview

LR-FHSS (Long Range Frequency Hopping Spread Spectrum) is a modulation technique designed for large-scale IoT networks, providing improved scalability and reliability compared to conventional LoRa-based systems.

This repository contains an adapted version of the original **LR-FHSS-Sim** simulator. The objective of this work is to extend the simulator capabilities by introducing:

- Modeling of **limited and imperfect Successive Interference Cancellation (SIC)** to evaluate its impact on packet decoding reliability.
- Integration of **radio propagation models** to enable more realistic wireless channel simulations.
- Enhanced evaluation of LR-FHSS network performance under realistic deployment conditions.

## Original Simulator

This work is based on the LR-FHSS-Sim simulator developed by the original authors.

Original repository:
[Link to LR-FHSS-Sim]

The original simulator provides a framework for simulating LR-FHSS networks and evaluating their performance in large-scale IoT scenarios.

## Main Contributions

The modifications introduced in this version include:

- [ ] Implementation of limited SIC capabilities.
- [ ] Modeling of imperfect SIC behavior.
- [ ] Integration of radio propagation effects (path loss, shadowing, fading, etc.).
- [ ] Evaluation of reliability metrics under different network conditions.

## Simulation Configurations

This repository includes several simulation scripts designed to evaluate LR-FHSS performance under different channel propagation conditions:

- `halifax.py`: runs simulations using the **Halifax radio propagation model**.
- `beyrouth_rural.py`: runs simulations using the **Beirut rural propagation model**.
- `beyrouth_urban.py`: runs simulations using the **Beirut urban propagation model**.

Each script is associated with a specific radio propagation model and can be used to analyze network performance under different deployment environments.

The file:

- `run.py`: runs LR-FHSS simulations without radio channel modeling, assuming an ideal propagation environment.
