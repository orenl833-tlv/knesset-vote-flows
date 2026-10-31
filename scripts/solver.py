"""FISTA for  min_P  sum_i w_i ||x_i P - y_i||^2  with every row of P on the probability simplex."""
import numpy as np


def project_rows_to_simplex(V):
    """Euclidean projection of each row of V onto the probability simplex (sort-based)."""
    n, m = V.shape
    U = -np.sort(-V, axis=1)                       # descending
    css = np.cumsum(U, axis=1) - 1.0
    ind = np.arange(1, m + 1)
    cond = (U - css / ind) > 0
    rho = m - 1 - np.argmax(cond[:, ::-1], axis=1)  # last index where the condition holds
    theta = css[np.arange(n), rho] / (rho + 1.0)
    return np.maximum(V - theta[:, None], 0.0)


def fista(X, Y, w, tol=1e-6, max_iter=50000, P0=None):
    """Solve the simplex-constrained weighted least squares.

    X: n x k earlier shares, Y: n x m later shares, w: length-n weights (normalised here to mean 1).
    Returns (P, info) with info = dict(iters, converged, objective, L).
    """
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    w = np.asarray(w, dtype=float)
    w = w / w.mean()
    n, k = X.shape
    m = Y.shape[1]
    XtWX = X.T @ (w[:, None] * X)
    XtWY = X.T @ (w[:, None] * Y)
    lam = float(np.linalg.eigvalsh(XtWX)[-1])
    L = 2.0 * lam
    if not L > 0:
        raise ValueError('degenerate design: lambda_max(X^T W X) = 0')
    step = 1.0 / L
    P = np.full((k, m), 1.0 / m) if P0 is None else np.asarray(P0, dtype=float).copy()
    Z = P.copy()
    t = 1.0
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        grad = 2.0 * (XtWX @ Z - XtWY)
        P_new = project_rows_to_simplex(Z - step * grad)
        t_new = 0.5 * (1.0 + np.sqrt(1.0 + 4.0 * t * t))
        Z = P_new + ((t - 1.0) / t_new) * (P_new - P)
        dmax = float(np.max(np.abs(P_new - P)))
        P, t = P_new, t_new
        if dmax < tol:
            converged = True
            break
    resid = X @ P - Y
    obj = float(np.sum(w[:, None] * resid * resid))
    return P, dict(iters=it, converged=converged, objective=obj, L=L)
