"""
test_q5_integration.py

Full-pipeline integration test for Q5 output data.
Runs preprocess -> register -> compute_deviations -> compute_statistics
on a synthetic L-shape with known excess + deficit zones.

Verified:
  1. Material split: within + over + under == 100.000000%
  2. worst_points: N=10, sorted by |dev| desc, first |dev| == max_abs_deviation
  3. Masking: within_tolerance_coarse + absorbed_within_tol_pct == within_tolerance (best-fit)
  4. PDF: colorbar legend, over/under rows, tech interpretation, worst-points table

Run:
    C:/module/.venv/Scripts/python.exe tests/test_q5_integration.py
or:
    pytest tests/test_q5_integration.py -v -s
"""

import io
import logging
import os
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import open3d as o3d

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.algorithms.preprocessing import preprocess_pipeline
from core.algorithms.registration  import register_pipeline
from core.algorithms.deviation      import compute_deviations, compute_statistics
from core.algorithms.report         import generate_report

logging.basicConfig(level=logging.WARNING)


# ── Synthetic geometry ────────────────────────────────────────────────────────

def _make_L_shape() -> o3d.geometry.TriangleMesh:
    """L-shape: long arm 100×30×20mm + short arm 30×30×40mm at x=[70,100], z=[20,60]."""
    arm1 = o3d.geometry.TriangleMesh.create_box(100.0, 30.0, 20.0)
    arm2 = o3d.geometry.TriangleMesh.create_box(30.0, 30.0, 40.0)
    arm2.translate([70.0, 0.0, 20.0])
    mesh = arm1 + arm2
    mesh.compute_vertex_normals()
    mesh.compute_triangle_normals()
    return mesh


def _make_defective_scan(
    mesh: o3d.geometry.TriangleMesh,
    n_points: int = 10_000,
    noise_std: float = 0.05,
    defect_mm: float = 2.5,
    seed: int = 42,
) -> tuple:
    """
    Scan with two deterministic defect zones:
      excess   (+defect_mm outward along Z) on top face of short arm:
                z > 57 mm AND x > 68 mm  (short arm top)
      deficit  (-defect_mm inward along Z) on bottom face of long arm:
                z < 1 mm AND x < 68 mm   (long arm bottom)

    Returns (pcd, n_excess_raw, n_deficit_raw).
    The scan is displaced 8 mm along X + 3 deg around Z so the pipeline
    must actually do registration work.
    """
    try:
        pcd = mesh.sample_points_uniformly(n_points, seed=seed)
    except TypeError:
        pcd = mesh.sample_points_uniformly(n_points)

    rng = np.random.default_rng(seed)
    pts = np.asarray(pcd.points).copy()

    # Small positional noise on all points
    pts += rng.normal(0.0, noise_std, pts.shape)

    # Excess: top of short arm pushed OUTWARD (+Z)
    # Outward normal of top face (z≈60) is +Z → pushing +Z = outside mesh = positive dev
    mask_excess = (pts[:, 2] > 57.0) & (pts[:, 0] > 68.0)
    pts[mask_excess, 2] += defect_mm
    n_excess = int(mask_excess.sum())

    # Deficit: left face of long arm pushed INWARD (+X direction)
    # Left face x=0, outward normal is -X.  Moving point to +X means the vector
    # (from closest face point to scan point) points in +X, opposite to normal -X
    # → dot < 0 → heuristic sign = negative → under_material_pct increases.
    mask_deficit = (pts[:, 0] < 1.0) & (pts[:, 1] < 30.0) & (pts[:, 2] < 20.0)
    pts[mask_deficit, 0] += defect_mm
    n_deficit = int(mask_deficit.sum())

    pcd.points = o3d.utility.Vector3dVector(pts)

    # Apply rigid displacement so registration has real work to do
    angle = np.deg2rad(3.0)
    c, s  = np.cos(angle), np.sin(angle)
    R     = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)
    t     = np.array([8.0, 0.0, 0.0])
    pts2  = (R @ np.asarray(pcd.points).T).T + t
    pcd.points = o3d.utility.Vector3dVector(pts2)

    return pcd, n_excess, n_deficit


_CONFIG = {
    "preprocessing": {
        "sor_neighbors": 20,
        "sor_std_ratio":  2.0,
        "voxel_size":    -1,
    },
    "registration": {
        "ransac_max_iter": 200_000,
        "ransac_n_starts": 6,
        "icp_max_iter":    150,
        "icp_coarse_pct":  5.0,
        "icp_fine_pct":    1.0,
        "alignment_mode":  "best_fit",
    },
    "analysis": {
        "tolerance_mm":          0.5,
        "conformance_threshold": 95,
        "worst_points_n":        10,
    },
    "ui": {
        "colormap": "RdYlGn_r",
    },
}


def _run_full_pipeline(pcd, mesh, config):
    """
    Mirrors worker.py: preprocess -> register -> deviations -> statistics.
    Returns (stats, reg_diag, deviations, pcd_registered, pcd_clean, T_total).
    """
    pcd_clean, pcd_down, voxel_size = preprocess_pipeline(pcd, config)
    pcd_reg, T_total, icp_rmse, suspect, reg_diag = register_pipeline(
        pcd_clean, pcd_down, mesh, config, pcd_voxel_size=voxel_size,
    )
    deviations, ambiguous_mask = compute_deviations(pcd_reg, mesh)

    tol    = config["analysis"]["tolerance_mm"]
    worst_n = int(config["analysis"].get("worst_points_n", 10))
    stats = compute_statistics(
        deviations, tol,
        ambiguous_mask=ambiguous_mask,
        point_coords=np.asarray(pcd_reg.points),
        worst_n=worst_n,
    )
    stats["registration_rmse"]    = icp_rmse
    stats["registration_suspect"] = suspect
    stats.update(reg_diag)
    return stats, reg_diag, deviations, pcd_reg, pcd_clean, T_total


# ── Shared fixture (computed once at module level during standalone run) ───────

_SHARED: dict = {}   # populated by _ensure_shared()

def _ensure_shared():
    if _SHARED:
        return
    mesh = _make_L_shape()
    pcd, n_excess, n_deficit = _make_defective_scan(mesh)
    (stats, reg_diag, deviations, pcd_reg,
     pcd_clean, T_total) = _run_full_pipeline(pcd, mesh, _CONFIG)
    _SHARED.update(
        mesh=mesh, pcd=pcd, stats=stats, reg_diag=reg_diag,
        deviations=deviations, pcd_reg=pcd_reg,
        pcd_clean=pcd_clean, T_total=T_total,
        n_excess=n_excess, n_deficit=n_deficit,
    )


# ── Test 1: material split invariant ─────────────────────────────────────────

def test_material_split_invariant():
    """within + over + under == exactly 100.000000%"""
    _ensure_shared()
    stats = _SHARED["stats"]

    within = stats["within_tolerance"]  * 100
    over   = stats["over_material_pct"] * 100
    under  = stats["under_material_pct"] * 100
    total  = within + over + under

    print("\n[Q5.1  Material split invariant]")
    print(f"  within_tolerance   = {within:8.4f} %")
    print(f"  over_material_pct  = {over:8.4f} %")
    print(f"  under_material_pct = {under:8.4f} %")
    print(f"  SUM                = {total:.10f} %")

    assert abs(total - 100.0) < 1e-6, f"sum = {total:.10f} % != 100%"
    assert over  > 0.0, "Expected excess-material points (short arm top bulge)"
    assert under > 0.0, "Expected deficit-material points (long arm bottom dent)"
    print("  PASS")


# ── Test 2: worst_points ──────────────────────────────────────────────────────

def test_worst_points():
    """N=10, sorted desc by |dev|, worst_points[0].|dev| == max_abs_deviation."""
    _ensure_shared()
    stats = _SHARED["stats"]

    wp      = stats.get("worst_points")
    max_abs = stats["max_abs_deviation"]

    print("\n[Q5.2  worst_points]")
    print(f"  max_abs_deviation  = {max_abs:.4f} mm")

    assert wp is not None, "stats missing 'worst_points'"
    assert len(wp) == 10,  f"Expected 10 entries, got {len(wp)}"

    first_abs = abs(wp[0]["dev"])
    print(f"  |worst_points[0].dev| = {first_abs:.4f} mm  (== max_abs: {abs(first_abs-max_abs)<1e-8})")
    assert abs(first_abs - max_abs) < 1e-8, (
        f"|wp[0].dev|={first_abs:.8f} != max_abs={max_abs:.8f}"
    )

    abs_devs = [abs(p["dev"]) for p in wp]
    assert abs_devs == sorted(abs_devs, reverse=True), \
        "worst_points is not sorted descending by |dev|"

    print(f"  {'#':>2}  {'x':>9}  {'y':>9}  {'z':>9}  {'dev':>10}")
    for i, pt in enumerate(wp, 1):
        print(f"  {i:2d}  {pt['x']:+9.3f}  {pt['y']:+9.3f}  "
              f"{pt['z']:+9.3f}  {pt['dev']:+10.4f} mm")
    print("  PASS")


# ── Test 3: masking metrics (Q4 extension) ────────────────────────────────────

def test_masking_metrics():
    """
    Invariant: within_tolerance_coarse + absorbed_within_tol_pct
               == within_tolerance_bestfit_down  (all on DOWNSAMPLED cloud — exact)

    Note: stats['within_tolerance'] is on the FULL registered cloud and will differ
    from within_tolerance_bestfit_down because the downsampled cloud is not the full
    cloud.  The correct algebraic check uses within_tolerance_bestfit_down.
    """
    _ensure_shared()
    stats = _SHARED["stats"]

    wtc    = stats.get("within_tolerance_coarse")
    abs_p  = stats.get("absorbed_within_tol_pct")
    wtbf_d = stats.get("within_tolerance_bestfit_down")   # on downsampled
    wtbf_f = stats["within_tolerance"]                    # on full cloud

    print("\n[Q4+Q5.3  Masking metrics]")
    assert wtc    is not None, "stats missing 'within_tolerance_coarse'"
    assert abs_p  is not None, "stats missing 'absorbed_within_tol_pct'"
    assert wtbf_d is not None, "stats missing 'within_tolerance_bestfit_down'"

    reconstructed = wtc + abs_p
    diff_down = abs(reconstructed - wtbf_d)
    diff_full = abs(reconstructed - wtbf_f)   # expected to be nonzero (different clouds)

    print(f"  within_tolerance_coarse        = {wtc*100:7.3f} %  (downsampled, T_coarse)")
    print(f"  absorbed_within_tol_pct        = {abs_p*100:+7.3f} pp")
    print(f"  within_tolerance_bestfit_down  = {wtbf_d*100:7.3f} %  (downsampled, T_fine)")
    print(f"  coarse + absorbed              = {reconstructed*100:7.3f} %")
    print(f"  diff vs bestfit_downsampled    = {diff_down:.2e}  (must be < 1e-9)")
    print(f"  within_tolerance (full cloud)  = {wtbf_f*100:7.3f} %  (for reference)")
    print(f"  diff full vs downsampled bestfit = {diff_full*100:.2f} pp  (expected nonzero)")

    assert diff_down < 1e-9, (
        f"coarse + absorbed = {reconstructed:.9f} "
        f"!= bestfit_downsampled = {wtbf_d:.9f}  (diff={diff_down:.2e})"
    )
    assert wtc >= 0.0 and wtc <= 1.0, "within_tolerance_coarse out of [0,1]"
    assert (wtc + abs_p) >= 0.0 and (wtc + abs_p) <= 1.0, \
        "within_tolerance_bestfit_down out of [0,1]"
    print("  PASS")


# ── Test 4: PDF generation and text content ───────────────────────────────────

def test_pdf_sections():
    """
    Generates a PDF and confirms (via pypdf text extraction) that all new Q5
    sections are present: colorbar legend header, over/under rows, tech
    interpretation, masking rows in diagnostics, worst-points table.
    """
    try:
        import pypdf
    except ImportError:
        print("\n[Q5.4  PDF] pypdf not installed — skipping text extraction")
        return

    _ensure_shared()
    stats      = _SHARED["stats"]
    deviations = _SHARED["deviations"]
    mesh       = _SHARED["mesh"]
    tol        = _CONFIG["analysis"]["tolerance_mm"]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = f.name

    try:
        generate_report(
            output_path=pdf_path,
            cad_path="L_shape.stl",
            scan_path="defective_scan.ply",
            deviations=deviations,
            stats=stats,
            registration_rmse=stats.get("registration_rmse", 0.0),
            screenshot_paths=None,
            mesh_triangles=len(mesh.triangles),
            config=_CONFIG,
            unit_cad="mm",
            unit_scan="mm",
        )

        reader     = pypdf.PdfReader(pdf_path)
        pages_text = [p.extract_text() or "" for p in reader.pages]
        all_text   = "\n".join(pages_text)
        p1, p2, p3 = pages_text[0], pages_text[1], pages_text[2] if len(pages_text) > 2 else ""

        over_pct  = stats["over_material_pct"]  * 100
        under_pct = stats["under_material_pct"] * 100

        print(f"\n[Q5.4  PDF sections]  pages={len(pages_text)}")

        # ── Colorbar legend header ─────────────────────────────────────────
        print("\n  -- Colorbar legend --")
        cb_found = ("шкалы" in p2.lower() or "шкалы" in all_text.lower() or
                    "legend" in all_text.lower())
        assert cb_found, "Colorbar legend section header not found"
        print(f"  Header 'Легенда цветовой шкалы': FOUND")

        # ── Over / under rows in results table ────────────────────────────
        print("\n  -- over / under rows (page 1) --")
        over_found  = ("збыток" in p1 or "Избыток" in p1)
        under_found = ("едостаток" in p1 or "Недостаток" in p1)
        assert over_found,  f"'Избыток материала' row missing from page 1"
        assert under_found, f"'Недостаток материала' row missing from page 1"
        print(f"  'Избыток материала'    : FOUND  value shown: {over_pct:.1f}%")
        print(f"  'Недостаток материала' : FOUND  value shown: {under_pct:.1f}%")

        # ── Tech interpretation block ──────────────────────────────────────
        print("\n  -- Технологическая интерпретация (page 1) --")
        interp_found = ("нтерпрета" in p1)
        assert interp_found, "Tech interpretation section missing from page 1"
        idx     = p1.find("нтерпрета")
        snippet = p1[max(0, idx - 20): idx + 250].replace("\n", " ")
        print(f"  FOUND. Snippet: ...{snippet[:200]}...")

        # ── Masking rows in diagnostics ────────────────────────────────────
        print("\n  -- Masking rows in diagnostics (page 1) --")
        mask_found = ("аскировка" in p1 or "Маскировка" in p1 or
                      "грубом" in p1.lower() or "допуске при" in p1.lower())
        assert mask_found, "Masking metric rows missing from diagnostic table"
        print(f"  Masking row: FOUND")

        # ── Worst-points table (page 3) ────────────────────────────────────
        print("\n  -- Worst-points table (page 3) --")
        wp_found = ("аибольш" in p3 or "худших" in p3.lower() or
                    "Откл" in p3 or "откл" in p3.lower() or "#" in p3)
        assert wp_found, (
            f"Worst-points table not found on page 3.\n"
            f"Page-3 content (first 400 chars):\n{p3[:400]}"
        )
        print(f"  Worst-points table: FOUND")

        # Show raw page text for the record
        print(f"\n  === Page 1 text (first 1200 chars) ===")
        print(p1[:1200])
        print(f"\n  === Page 3 text (first 600 chars) ===")
        print(p3[:600])

        print("\n  PASS — all 5 PDF sections verified")

    finally:
        try:
            os.unlink(pdf_path)
        except Exception:
            pass


# ── Test 5: transformation contract (CRIT-A1) ────────────────────────────────

def test_transformation_includes_centroid():
    """
    T_total из register_pipeline должна включать центроидное предвыравнивание:
    применение T_total к исходному pcd_full (вход register_pipeline) обязано
    воспроизводить pcd_registered. Это контракт NPZ-сайдкара и save/load_project.
    """
    import copy as _copy

    _ensure_shared()
    pcd_clean = _SHARED["pcd_clean"]
    pcd_reg   = _SHARED["pcd_reg"]
    T_total   = _SHARED["T_total"]

    assert T_total is not None, "register_pipeline вернул T_total=None"
    assert T_total.shape == (4, 4), f"T_total должна быть 4×4, получено {T_total.shape}"

    pcd_replay = _copy.deepcopy(pcd_clean).transform(T_total)
    replayed   = np.asarray(pcd_replay.points)
    expected   = np.asarray(pcd_reg.points)

    assert replayed.shape == expected.shape, (
        f"размеры расходятся: replay={replayed.shape} vs expected={expected.shape}"
    )

    diffs = np.linalg.norm(replayed - expected, axis=1)
    rmse  = float(np.sqrt(np.mean(diffs ** 2)))
    max_d = float(diffs.max())

    print(f"\n[CRIT-A1  Transformation contract]")
    print(f"  RMSE(T_total @ pcd_clean, pcd_registered) = {rmse:.3e} мм")
    print(f"  max|Δ|                                    = {max_d:.3e} мм")

    assert rmse < 1e-6, f"RMSE={rmse:.3e} мм > 1e-6 — T_centroid потерян"
    print("  PASS")


# ── Standalone runner ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    all_pass = True

    print("=" * 70)
    print("Q5 Integration verification  (full pipeline: preprocess→register→deviation)")
    print("=" * 70)

    print("\nBuilding shared fixture (L-shape + defective scan)...")
    _ensure_shared()
    print(f"  L-shape: arm1=100x30x20mm, arm2=30x30x40mm")
    print(f"  Scan: {_SHARED['pcd'].points.__len__()}-pt cloud, "
          f"excess={_SHARED['n_excess']} pts (+2.5mm top-of-short-arm), "
          f"deficit={_SHARED['n_deficit']} pts (-2.5mm bottom-of-long-arm)")
    print(f"  Pipeline: preprocess + register + C2M deviations + statistics")

    for fn in (test_material_split_invariant, test_worst_points,
               test_masking_metrics, test_pdf_sections,
               test_transformation_includes_centroid):
        print()
        print("-" * 70)
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL: {e}")
            traceback.print_exc()
            all_pass = False
        except Exception as e:
            print(f"  ERROR: {e}")
            traceback.print_exc()
            all_pass = False

    print()
    print("=" * 70)
    print("OVERALL:", "ALL PASS" if all_pass else "FAILURES — see above")
    sys.exit(0 if all_pass else 1)
