%% LR-FHSS — Combined SIC Model
%
%  Combined SIC model:
%    - imperfect SIC    -> gamma
%    - limited SIC depth -> L
%
%  Analytical density evolution model.
%
%  Efficiency:
%    eta = H * Ph
%
%  (no fragment contribution)
%
%  Author: Tanios (MATLAB conversion)

clear; clc; close all;

%% =========================================================
%  PARAMETERS
%% =========================================================

LAMBDA_RATE = 1 / 900;

TH = 0.233472;

C = 35;

R = 3;

% imperfect SIC quality
gamma_values = [1.0, 0.9, 0.7, 0.6];

% SIC iteration limits
L_values = [2, 3, 4, 6];   % 6 = practically unlimited SIC

MAX_ITER = 10000;

EPS = 1e-12;

%% =========================================================
%  NODE RANGE
%% =========================================================

N_values = 5000 : 1000 : 149000;

%% =========================================================
%  COLORS
%% =========================================================

color_map = containers.Map( ...
    {2,    3,        4,        6       }, ...
    {[0.161 0.502 0.725], ...   % #2980B9
     [0.153 0.682 0.376], ...   % #27AE60
     [0.902 0.494 0.133], ...   % #E67E22
     [0.557 0.267 0.678]});     % #8E44AD

%% =========================================================
%  MAIN LOOP
%% =========================================================

for gi = 1 : length(gamma_values)

    gamma = gamma_values(gi);

    figure('Position', [100 100 950 480]);
    hold on; grid on;

    fprintf('\n========================================\n');
    fprintf('gamma = %.1f\n', gamma);
    fprintf('========================================\n');

    for li = 1 : length(L_values)

        L = L_values(li);

        Ph_values  = zeros(1, length(N_values));
        Eta_values = zeros(1, length(N_values));

        % -------------------------------------------------
        %  Compute Ph and eta for each N
        % -------------------------------------------------

        for ni = 1 : length(N_values)

            N = N_values(ni);

            H = compute_H(N, LAMBDA_RATE, R, TH, C);

            [Ph, ~] = compute_Ph(N, gamma, L, LAMBDA_RATE, R, TH, C, MAX_ITER, EPS);

            eta = (H / R) * Ph;

            Ph_values(ni)  = Ph;
            Eta_values(ni) = eta;

        end

        % -------------------------------------------------
        %  Threshold (peak efficiency)
        % -------------------------------------------------

        [eta_peak, idx_peak] = max(Eta_values);

        N_star = N_values(idx_peak);

        fprintf('L = %d | threshold = %s | eta_max = %.4f\n', ...
            L, num2str(N_star, '%,d'), eta_peak);

        % -------------------------------------------------
        %  Plot
        % -------------------------------------------------

        col   = color_map(L);
        label = sprintf('L=%d | N*=%dk', L, round(N_star / 1000));

        plot(N_values / 1000, Eta_values, ...
            'LineWidth', 2, ...
            'Color',     col, ...
            'DisplayName', label);

        % threshold vertical line
        xline(N_star / 1000, ...
            'Color',     col, ...
            'LineStyle', ':', ...
            'Alpha',     0.5, ...
            'HandleVisibility', 'off');

    end

    % =====================================================
    %  Figure formatting
    % =====================================================

    xlabel('Number of end-devices (\times10^3)');
    ylabel('\eta = H \times P_h');
    title(sprintf('Combined LR-FHSS SIC Model (\\gamma = %.1f)', gamma));
    legend('Location', 'best');
    hold off;

end


%% =========================================================
%  LOCAL FUNCTIONS
%% =========================================================

function H = compute_H(N, lambda_rate, R, TH, C)
%COMPUTE_H  Compute offered load H for N nodes.
    mu = lambda_rate * N;
    H  = (2 * mu * R * TH) / C;
end


function [Ph, p_min] = compute_Ph(N, gamma, L, lambda_rate, R, TH, C, MAX_ITER, EPS)
%COMPUTE_PH  Header success probability via density evolution.

    H = compute_H(N, lambda_rate, R, TH, C);

    p_min = density_evolution(H, gamma, L, R, MAX_ITER, EPS);

    Ph = max(0, min(1, 1 - p_min^R));

end


function p_new = density_evolution(H, gamma, L, R, MAX_ITER, EPS)
%DENSITY_EVOLUTION  Fixed-point iteration for combined SIC model.
%
%  p_new = 1 - exp(-H) * SUM_{k=0}^{L-1} (H*gamma*(1-q))^k / k!

    p = 1.0;

    for iter = 1 : MAX_ITER

        % Variable-node update
        q = p^(R - 1);

        % Slot-node update  (truncated Poisson sum)
        x   = H * gamma * (1 - q);
        s   = 0.0;
        xpow = 1.0;  % x^k

        for k = 0 : L-1
            if k > 0
                xpow = xpow * x;
            end
            s = s + xpow / factorial(k);
        end

        p_new = 1 - exp(-H) * s;

        % Convergence check
        if abs(p_new - p) < EPS
            break;
        end

        p = p_new;

    end

end