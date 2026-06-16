from __future__ import annotations
import math
from scipy.stats import norm

def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "CE") -> float:
    """Black-Scholes-Merton option price."""
    if T <= 0:
        if option_type == "CE":
            return max(0.0, S - K)
        else:
            return max(0.0, K - S)
    if sigma <= 0:
        if option_type == "CE":
            return max(0.0, S - K * math.exp(-r * T))
        else:
            return max(0.0, K * math.exp(-r * T) - S)
            
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    if option_type == "CE":
        price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return max(0.0, price)


def bs_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Vega of option (derivative with respect to volatility)."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return S * math.sqrt(T) * norm.pdf(d1)


def calculate_iv(price: float, S: float, K: float, T: float, r: float, option_type: str = "CE") -> float:
    """Calculate implied volatility using Newton-Raphson with bisection fallback."""
    if T <= 0 or price <= 0:
        return 0.0
    
    intrinsic = (S - K) if option_type == "CE" else (K - S)
    if price <= max(0.0, intrinsic):
        return 0.0
        
    # Newton-Raphson
    sigma = 0.3  # reasonable starting point for IV
    for _ in range(50):
        p = bs_price(S, K, T, r, sigma, option_type)
        vega = bs_vega(S, K, T, r, sigma)
        if vega < 1e-4:
            break
        diff = p - price
        if abs(diff) < 1e-3:
            return sigma
        sigma = sigma - diff / vega
        if sigma <= 0.001:
            sigma = 0.001
        elif sigma > 3.0:
            sigma = 3.0
            
    # Bisection fallback
    low, high = 0.0001, 3.0
    for _ in range(20):
        mid = (low + high) / 2
        p = bs_price(S, K, T, r, mid, option_type)
        if abs(p - price) < 1e-2:
            return mid
        if p < price:
            low = mid
        else:
            high = mid
            
    return (low + high) / 2


def calculate_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "CE") -> dict[str, float]:
    """Calculate option Greeks: Delta, Gamma, Theta (daily), Vega (per 1%)."""
    if T <= 0 or sigma <= 0:
        if option_type == "CE":
            delta = 1.0 if S > K else (0.5 if S == K else 0.0)
        else:
            delta = -1.0 if S < K else (-0.5 if S == K else 0.0)
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
        
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    sqrt_T = math.sqrt(T)
    pdf_d1 = norm.pdf(d1)
    cdf_d1 = norm.cdf(d1)
    
    if option_type == "CE":
        delta = cdf_d1
        # Theta equation for call
        theta = -(S * pdf_d1 * sigma) / (2 * sqrt_T) - r * K * math.exp(-r * T) * norm.cdf(d2)
    else:
        delta = cdf_d1 - 1.0
        # Theta equation for put
        theta = -(S * pdf_d1 * sigma) / (2 * sqrt_T) + r * K * math.exp(-r * T) * norm.cdf(-d2)
        
    gamma = pdf_d1 / (S * sigma * sqrt_T)
    vega = S * sqrt_T * pdf_d1
    
    return {
        "delta": round(float(delta), 4),
        "gamma": round(float(gamma), 6),
        "theta": round(float(theta / 365.25), 4),  # Scaled per day
        "vega": round(float(vega / 100), 4)       # Scaled per 1% vol change
    }
