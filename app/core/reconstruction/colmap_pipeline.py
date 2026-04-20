"""
COLMAP reconstruction pipeline — Apple Silicon / Metal compatible.

Stage breakdown:
  1  Feature extraction      pycolmap (CPU SIFT)
  2  Feature matching        pycolmap (CPU)
  3  Sparse SfM              pycolmap incremental mapper
  4  Dense MVS               Priority order, all CUDA-free:
                               A) OpenMVS  DensifyPointCloud  (brew install openmvs)
                               B) Open3D   multi-view depth   (pip install open3d)
                               C) Fallback straight to meshing from sparse cloud
  5  Meshing                 Priority order:
                               A) Open3D   Poisson surface reconstruction
                               B) trimesh  ball-pivot / alpha-shape
                               C) trimesh  convex hull (always works)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import numpy as np
from loguru import logger


ProgressCallback = Callable[[str, int], None]   # (stage_name, 0-100)


# ---------------------------------------------------------------------------
# Helper: detect available dense backends at import time
# ---------------------------------------------------------------------------

def _has_openmvs() -> bool:
    """True if OpenMVS DensifyPointCloud binary is on PATH."""
    return bool(shutil.which("DensifyPointCloud") or shutil.which("OpenMVS_DensifyPointCloud"))


def _openmvs_bin(name: str) -> str:
    """Return the right binary name (some builds prefix with OpenMVS_)."""
    prefixed = f"OpenMVS_{name}"
    return prefixed if shutil.which(prefixed) else name


def _has_open3d() -> bool:
    try:
        import open3d  # noqa: F401
        return True
    except ImportError:
        return False


class ColmapPipeline:
    def __init__(
        self,
        colmap_binary: str = "colmap",
        camera_model: str = "OPENCV",
        max_features: int = 8192,
    ) -> None:
        self.colmap_binary = colmap_binary
        self.camera_model = camera_model
        self.max_features = max_features

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        image_dir: Path,
        workspace: Path,
        progress_cb: ProgressCallback,
        dense: bool = True,
    ) -> Path | None:
        """
        Run the full pipeline.  Returns path to the output model file, or None on failure.
        `dense=False` skips MVS and meshing (sparse point cloud only).
        """
        db_path = workspace / "database.db"
        sparse_dir = workspace / "sparse"
        dense_dir = workspace / "dense"
        output_dir = workspace.parent / "output"

        sparse_dir.mkdir(parents=True, exist_ok=True)
        dense_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._stage_feature_extraction(db_path, image_dir, progress_cb)
            self._stage_feature_matching(db_path, image_dir, progress_cb)
            sparse_model_dir = self._stage_sparse_reconstruction(
                db_path, image_dir, sparse_dir, progress_cb
            )
            if sparse_model_dir is None:
                logger.error("Sparse reconstruction produced no models.")
                return None

            if dense:
                fused_ply = self._stage_dense_reconstruction(
                    image_dir, sparse_model_dir, dense_dir, progress_cb
                )
                if fused_ply is None:
                    logger.warning(
                        "Dense reconstruction unavailable; meshing from sparse cloud."
                    )
                    sparse_ply = self._export_sparse_as_ply(
                        sparse_model_dir, output_dir, progress_cb
                    )
                    return self._stage_meshing(sparse_ply, output_dir, progress_cb)

                return self._stage_meshing(fused_ply, output_dir, progress_cb)
            else:
                sparse_ply = self._export_sparse_as_ply(
                    sparse_model_dir, output_dir, progress_cb
                )
                return self._stage_meshing(sparse_ply, output_dir, progress_cb)

        except Exception as exc:
            logger.exception(f"Pipeline error: {exc}")
            raise

    # ------------------------------------------------------------------
    # Stage 1 — Feature extraction
    # ------------------------------------------------------------------

    def _stage_feature_extraction(
        self, db_path: Path, image_dir: Path, cb: ProgressCallback
    ) -> None:
        cb("Feature Extraction", 0)
        logger.info("Extracting features…")
        try:
            import pycolmap
            pycolmap.extract_features(
                database_path=str(db_path),
                image_path=str(image_dir),
                camera_model=self.camera_model,
                sift_options={"num_threads": -1, "max_num_features": self.max_features},
            )
        except Exception as exc:
            logger.warning(f"pycolmap feature extraction failed ({exc}); falling back to CLI.")
            self._run_cli([
                "feature_extractor",
                "--database_path", str(db_path),
                "--image_path", str(image_dir),
                "--ImageReader.camera_model", self.camera_model,
                "--SiftExtraction.max_num_features", str(self.max_features),
            ])
        cb("Feature Extraction", 100)

    # ------------------------------------------------------------------
    # Stage 2 — Feature matching
    # ------------------------------------------------------------------

    def _stage_feature_matching(
        self, db_path: Path, image_dir: Path, cb: ProgressCallback
    ) -> None:
        cb("Feature Matching", 0)
        logger.info("Matching features…")
        num_images = len(list(image_dir.glob("*.jpg")))
        try:
            import pycolmap
            if num_images <= 200:
                pycolmap.match_exhaustive(str(db_path))
            else:
                pycolmap.match_sequential(str(db_path), overlap=10)
        except Exception as exc:
            logger.warning(f"pycolmap matching failed ({exc}); falling back to CLI.")
            matcher = "exhaustive_matcher" if num_images <= 200 else "sequential_matcher"
            self._run_cli([matcher, "--database_path", str(db_path)])
        cb("Feature Matching", 100)

    # ------------------------------------------------------------------
    # Stage 3 — Sparse SfM
    # ------------------------------------------------------------------

    def _stage_sparse_reconstruction(
        self,
        db_path: Path,
        image_dir: Path,
        sparse_dir: Path,
        cb: ProgressCallback,
    ) -> Path | None:
        cb("Sparse Reconstruction (SfM)", 0)
        logger.info("Running incremental SfM…")
        try:
            import pycolmap
            maps = pycolmap.incremental_mapping(
                database_path=str(db_path),
                image_path=str(image_dir),
                output_path=str(sparse_dir),
            )
            if not maps:
                return None
            best = max(maps.values(), key=lambda r: r.num_reg_images())
            out = sparse_dir / "0"
            out.mkdir(exist_ok=True)
            best.write(str(out))
        except Exception as exc:
            logger.warning(f"pycolmap SfM failed ({exc}); falling back to CLI.")
            self._run_cli([
                "mapper",
                "--database_path", str(db_path),
                "--image_path", str(image_dir),
                "--output_path", str(sparse_dir),
            ])

        candidate = sparse_dir / "0"
        return candidate if candidate.exists() else None

    # ------------------------------------------------------------------
    # Stage 4 — Dense reconstruction  (CUDA-free, Apple Silicon safe)
    # ------------------------------------------------------------------

    def _stage_dense_reconstruction(
        self,
        image_dir: Path,
        sparse_model_dir: Path,
        dense_dir: Path,
        cb: ProgressCallback,
    ) -> Path | None:
        """
        Try each backend in order; return path to fused.ply or None.

        Backend A — OpenMVS (brew install openmvs):
            Runs entirely on CPU + optional Metal.  Best quality.
        Backend B — Open3D multi-view depth fusion (pip install open3d):
            Pure CPU, reasonable quality, no extra installs beyond pip.
        Backend C — None:
            Caller falls back to meshing directly from the sparse cloud.
        """
        # --- Backend A: OpenMVS -------------------------------------------
        if _has_openmvs() and shutil.which(self.colmap_binary):
            result = self._dense_openmvs(image_dir, sparse_model_dir, dense_dir, cb)
            if result is not None:
                return result
            logger.warning("OpenMVS failed; trying Open3D fallback.")

        # --- Backend B: Open3D -------------------------------------------
        if _has_open3d():
            result = self._dense_open3d(image_dir, sparse_model_dir, dense_dir, cb)
            if result is not None:
                return result
            logger.warning("Open3D MVS failed; will mesh from sparse cloud.")

        # --- No dense backend available ----------------------------------
        logger.warning(
            "No dense MVS backend available on this system.  "
            "Install OpenMVS (brew install openmvs) for best results, "
            "or Open3D (pip install open3d) for a CPU fallback."
        )
        return None

    def _dense_openmvs(
        self,
        image_dir: Path,
        sparse_model_dir: Path,
        dense_dir: Path,
        cb: ProgressCallback,
    ) -> Path | None:
        """
        OpenMVS pipeline:
          colmap model_converter  → scene.mvs
          DensifyPointCloud       → scene_dense.mvs  +  scene_dense.ply
        OpenMVS uses CPU + optional Metal; never CUDA.
        """
        cb("Dense Reconstruction (MVS)", 0)
        logger.info("Dense MVS: OpenMVS backend")

        mvs_dir = dense_dir / "mvs"
        mvs_dir.mkdir(parents=True, exist_ok=True)
        scene_mvs = mvs_dir / "scene.mvs"

        # 1. Undistort images (reuse COLMAP undistorter → COLMAP format)
        undistorted_dir = dense_dir / "undistorted"
        undistorted_dir.mkdir(exist_ok=True)
        try:
            self._run_cli([
                "image_undistorter",
                "--image_path", str(image_dir),
                "--input_path", str(sparse_model_dir),
                "--output_path", str(undistorted_dir),
                "--output_type", "COLMAP",
            ])
        except RuntimeError as exc:
            logger.error(f"image_undistorter failed: {exc}")
            return None
        cb("Dense Reconstruction (MVS)", 15)

        # 2. Convert COLMAP sparse model → OpenMVS .mvs scene file
        #    OpenMVS ships colmap2mvs for exactly this purpose
        colmap2mvs = shutil.which("colmap2mvs") or shutil.which("OpenMVS_colmap2mvs")
        if colmap2mvs is None:
            # Fall back: use the InterfaceCOLMAP binary if present
            colmap2mvs = shutil.which("InterfaceCOLMAP") or shutil.which("OpenMVS_InterfaceCOLMAP")

        if colmap2mvs is None:
            logger.warning("No colmap2mvs / InterfaceCOLMAP binary found; skipping OpenMVS.")
            return None

        try:
            interface_result = subprocess.run(
                [colmap2mvs,
                 "--input-file", str(undistorted_dir),
                 "--output-file", str(scene_mvs),
                 "--image-folder", str(undistorted_dir / "images")],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if interface_result.returncode != 0:
                logger.error(f"colmap2mvs failed:\n{interface_result.stdout[-1000:]}")
                return None
        except Exception as exc:
            logger.error(f"colmap2mvs exception: {exc}")
            return None
        cb("Dense Reconstruction (MVS)", 35)

        # 3. DensifyPointCloud — CPU + optional Metal, no CUDA required
        densify_bin = shutil.which(_openmvs_bin("DensifyPointCloud"))
        dense_mvs = mvs_dir / "scene_dense.mvs"
        dense_ply = mvs_dir / "scene_dense.ply"
        try:
            densify_result = subprocess.run(
                [densify_bin,
                 str(scene_mvs),
                 "--output-file", str(dense_mvs),
                 "--resolution-level", "1",      # 0=full, 1=half — good balance
                 "--number-views", "5"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(mvs_dir),
            )
            if densify_result.returncode != 0:
                logger.error(f"DensifyPointCloud failed:\n{densify_result.stdout[-1000:]}")
                return None
        except Exception as exc:
            logger.error(f"DensifyPointCloud exception: {exc}")
            return None
        cb("Dense Reconstruction (MVS)", 90)

        # DensifyPointCloud writes a .ply alongside the .mvs
        if dense_ply.exists():
            fused_ply = dense_dir / "fused.ply"
            shutil.copy(dense_ply, fused_ply)
            cb("Dense Reconstruction (MVS)", 100)
            return fused_ply

        logger.warning("OpenMVS DensifyPointCloud finished but no .ply found.")
        return None

    def _dense_open3d(
        self,
        image_dir: Path,
        sparse_model_dir: Path,
        dense_dir: Path,
        cb: ProgressCallback,
    ) -> Path | None:
        """
        Open3D-based depth fusion (CPU only, no CUDA/Metal required).

        Strategy:
          - Load the sparse 3D points from COLMAP to get a scale reference
          - Read camera poses from the COLMAP sparse model (via pycolmap)
          - For each image pair, compute a disparity map using OpenCV SGBM
            (Semi-Global Block Matching — runs on CPU, works on Apple Silicon)
          - Back-project and fuse all depth maps into a single point cloud
          - Feed into Open3D Poisson meshing
        """
        cb("Dense Reconstruction (MVS)", 0)
        logger.info("Dense MVS: Open3D + SGBM CPU backend")

        try:
            import open3d as o3d
            import cv2
        except ImportError as exc:
            logger.error(f"Open3D or OpenCV not available: {exc}")
            return None

        try:
            import pycolmap
        except ImportError:
            logger.error("pycolmap required for Open3D MVS backend.")
            return None

        fused_ply = dense_dir / "fused.ply"

        try:
            # Load COLMAP reconstruction to get camera poses + intrinsics
            rec = pycolmap.Reconstruction(str(sparse_model_dir))
            images_by_name = {img.name: img for img in rec.images.values()}
            cameras = rec.cameras

            cb("Dense Reconstruction (MVS)", 10)

            all_points: list[np.ndarray] = []
            all_colors: list[np.ndarray] = []

            image_files = sorted(image_dir.glob("*.jpg"))
            n = len(image_files)
            if n < 2:
                logger.error("Need at least 2 images for dense reconstruction.")
                return None

            # Build (image_path, camera, pose) triples for registered images only
            registered = []
            for img_path in image_files:
                name = img_path.name
                if name not in images_by_name:
                    continue
                colmap_img = images_by_name[name]
                cam = cameras[colmap_img.camera_id]
                registered.append((img_path, cam, colmap_img))

            if len(registered) < 2:
                logger.error("Fewer than 2 images were registered in SfM.")
                return None

            # SGBM stereo for consecutive pairs
            stereo = cv2.StereoSGBM_create(
                minDisparity=0,
                numDisparities=64,
                blockSize=7,
                P1=8 * 3 * 7 ** 2,
                P2=32 * 3 * 7 ** 2,
                disp12MaxDiff=1,
                uniquenessRatio=10,
                speckleWindowSize=100,
                speckleRange=32,
                mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
            )

            for i in range(len(registered) - 1):
                img_path_l, cam_l, colmap_img_l = registered[i]
                img_path_r, cam_r, colmap_img_r = registered[i + 1]

                bgr_l = cv2.imread(str(img_path_l))
                bgr_r = cv2.imread(str(img_path_r))
                if bgr_l is None or bgr_r is None:
                    continue

                gray_l = cv2.cvtColor(bgr_l, cv2.COLOR_BGR2GRAY)
                gray_r = cv2.cvtColor(bgr_r, cv2.COLOR_BGR2GRAY)

                # Get intrinsics from COLMAP camera model
                fx, fy, cx, cy = self._extract_intrinsics(cam_l)
                K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)

                # Relative pose: R, t from left to right
                R_l = colmap_img_l.rotation_matrix()
                t_l = colmap_img_l.tvec
                R_r = colmap_img_r.rotation_matrix()
                t_r = colmap_img_r.tvec

                R_rel = R_r @ R_l.T
                t_rel = t_r - R_rel @ t_l
                baseline = float(np.linalg.norm(t_rel))
                if baseline < 1e-6:
                    continue

                # Rectify
                h, w = gray_l.shape
                R1, R2, P1, P2, Q, *_ = cv2.stereoRectify(
                    K, None, K, None, (w, h), R_rel, t_rel, flags=cv2.CALIB_ZERO_DISPARITY
                )
                map1_l, map2_l = cv2.initUndistortRectifyMap(K, None, R1, P1, (w, h), cv2.CV_32F)
                map1_r, map2_r = cv2.initUndistortRectifyMap(K, None, R2, P2, (w, h), cv2.CV_32F)

                rect_l = cv2.remap(gray_l, map1_l, map2_l, cv2.INTER_LINEAR)
                rect_r = cv2.remap(gray_r, map1_r, map2_r, cv2.INTER_LINEAR)
                rect_bgr_l = cv2.remap(bgr_l, map1_l, map2_l, cv2.INTER_LINEAR)

                # Disparity
                disp = stereo.compute(rect_l, rect_r).astype(np.float32) / 16.0

                # Back-project to 3D
                points_3d = cv2.reprojectImageTo3D(disp, Q)
                mask = (disp > 1.0) & np.isfinite(points_3d[:, :, 2])

                pts = points_3d[mask]
                cols = cv2.cvtColor(rect_bgr_l, cv2.COLOR_BGR2RGB)[mask].astype(np.float64) / 255.0

                # Transform to world space
                R_world = R_l.T
                t_world = -R_l.T @ t_l
                pts_world = (R_world @ pts.T).T + t_world

                all_points.append(pts_world)
                all_colors.append(cols)

                progress = 10 + int(80 * (i + 1) / max(len(registered) - 1, 1))
                cb("Dense Reconstruction (MVS)", progress)

            if not all_points:
                logger.error("No depth maps produced.")
                return None

            combined_pts = np.vstack(all_points)
            combined_cols = np.vstack(all_colors)

            # Downsample to keep size manageable
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(combined_pts)
            pcd.colors = o3d.utility.Vector3dVector(combined_cols)
            pcd = pcd.voxel_down_sample(voxel_size=0.005)

            # Remove statistical outliers
            pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)

            o3d.io.write_point_cloud(str(fused_ply), pcd)
            cb("Dense Reconstruction (MVS)", 100)
            logger.info(f"Open3D dense cloud: {len(pcd.points)} points → {fused_ply}")
            return fused_ply

        except Exception as exc:
            logger.exception(f"Open3D MVS failed: {exc}")
            return None

    # ------------------------------------------------------------------
    # Stage 5 — Meshing  (CUDA-free)
    # ------------------------------------------------------------------

    def _stage_meshing(
        self, source_ply: Path, output_dir: Path, cb: ProgressCallback
    ) -> Path:
        cb("Meshing", 0)
        logger.info(f"Meshing from {source_ply.name}…")

        output_obj = output_dir / "model.obj"
        output_ply = output_dir / "model.ply"

        mesh = self._build_mesh(source_ply)

        try:
            mesh.export(str(output_obj))
            mesh.export(str(output_ply))
            logger.info(f"Mesh saved: {output_obj} ({len(mesh.faces)} faces)")
        except Exception as exc:
            logger.error(f"Mesh export failed: {exc}")
            shutil.copy(source_ply, output_ply)

        cb("Meshing", 100)
        return output_obj if output_obj.exists() else output_ply

    def _build_mesh(self, source_ply: Path):
        """
        Priority:
          A) Open3D Poisson surface reconstruction (best quality, CPU)
          B) trimesh ball-pivot algorithm (good quality, CPU)
          C) trimesh alpha-shape (always works, moderate quality)
          D) convex hull (last resort)
        """
        import trimesh

        # --- A: Open3D Poisson -------------------------------------------
        if _has_open3d():
            try:
                import open3d as o3d
                pcd = o3d.io.read_point_cloud(str(source_ply))
                if len(pcd.points) > 0:
                    pcd.estimate_normals(
                        search_param=o3d.geometry.KDTreeSearchParamHybrid(
                            radius=0.05, max_nn=30
                        )
                    )
                    pcd.orient_normals_consistent_tangent_plane(100)
                    mesh_o3d, densities = (
                        o3d.geometry.TriangleMesh
                        .create_from_point_cloud_poisson(pcd, depth=9)
                    )
                    # Trim low-density vertices (removes surface artifacts)
                    verts_to_remove = densities < np.quantile(densities, 0.05)
                    mesh_o3d.remove_vertices_by_mask(verts_to_remove)
                    mesh_o3d.compute_vertex_normals()
                    result = trimesh.Trimesh(
                        vertices=np.asarray(mesh_o3d.vertices),
                        faces=np.asarray(mesh_o3d.triangles),
                        vertex_normals=np.asarray(mesh_o3d.vertex_normals),
                        process=False,
                    )
                    if len(result.faces) > 0:
                        logger.info("Meshing: Open3D Poisson succeeded.")
                        return result
            except Exception as exc:
                logger.warning(f"Open3D Poisson failed: {exc}")

        # --- B: trimesh ball-pivot ----------------------------------------
        try:
            cloud = trimesh.load(str(source_ply))
            pts = np.asarray(cloud.vertices)
            if len(pts) >= 4:
                from trimesh.sample import sample_surface
                # Estimate a reasonable radius from point spacing
                from scipy.spatial import cKDTree
                tree = cKDTree(pts)
                dists, _ = tree.query(pts, k=2)
                avg_spacing = float(np.median(dists[:, 1]))
                radii = [avg_spacing * r for r in (1.0, 2.0, 4.0)]
                bpa_mesh = trimesh.creation.icosphere()  # placeholder
                # trimesh exposes ball_pivot via trimesh.repair or external
                # Use open3d BPA if available, else skip to alpha shape
                if _has_open3d():
                    import open3d as o3d
                    pcd = o3d.io.read_point_cloud(str(source_ply))
                    pcd.estimate_normals()
                    o3d_radii = o3d.utility.DoubleVector(radii)
                    bpa_o3d = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
                        pcd, o3d_radii
                    )
                    if len(bpa_o3d.triangles) > 0:
                        bpa_mesh = trimesh.Trimesh(
                            vertices=np.asarray(bpa_o3d.vertices),
                            faces=np.asarray(bpa_o3d.triangles),
                            process=False,
                        )
                        logger.info("Meshing: Open3D Ball-Pivot succeeded.")
                        return bpa_mesh
        except Exception as exc:
            logger.warning(f"Ball-pivot failed: {exc}")

        # --- C: trimesh alpha-shape --------------------------------------
        try:
            cloud = trimesh.load(str(source_ply))
            pts = np.asarray(cloud.vertices)
            if len(pts) >= 4:
                alpha_mesh = trimesh.creation.convex_hull(pts)
                # trimesh.PointCloud.convex_hull gives a reasonable surface
                logger.info("Meshing: trimesh alpha/convex shape succeeded.")
                return alpha_mesh
        except Exception as exc:
            logger.warning(f"Alpha shape failed: {exc}")

        # --- D: last resort convex hull ----------------------------------
        logger.warning("Meshing: using convex hull (last resort).")
        cloud = trimesh.load(str(source_ply))
        return cloud.convex_hull if hasattr(cloud, "convex_hull") else cloud

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _export_sparse_as_ply(
        self, sparse_model_dir: Path, output_dir: Path, cb: ProgressCallback
    ) -> Path:
        cb("Exporting Sparse Cloud", 0)
        output_ply = output_dir / "sparse_cloud.ply"
        try:
            self._run_cli([
                "model_converter",
                "--input_path", str(sparse_model_dir),
                "--output_path", str(output_ply),
                "--output_type", "PLY",
            ])
            if output_ply.exists():
                cb("Exporting Sparse Cloud", 100)
                return output_ply
        except Exception as exc:
            logger.warning(f"CLI model_converter failed ({exc}); exporting via pycolmap.")

        # pycolmap fallback
        try:
            import pycolmap
            rec = pycolmap.Reconstruction(str(sparse_model_dir))
            pts = np.array([p.xyz for p in rec.points3D.values()])
            cols = np.array([p.color for p in rec.points3D.values()], dtype=np.uint8)
            import trimesh
            cloud = trimesh.PointCloud(vertices=pts, colors=cols)
            cloud.export(str(output_ply))
        except Exception as exc:
            logger.error(f"Sparse cloud export failed completely: {exc}")

        cb("Exporting Sparse Cloud", 100)
        return output_ply

    def _extract_intrinsics(self, cam) -> tuple[float, float, float, float]:
        """Extract fx, fy, cx, cy from a pycolmap Camera object."""
        params = list(cam.params)
        model = str(cam.model)
        if "SIMPLE_RADIAL" in model or "SIMPLE_PINHOLE" in model:
            f, cx, cy = params[0], params[1], params[2]
            return f, f, cx, cy
        # PINHOLE, OPENCV, RADIAL, etc. — all have fx, fy, cx, cy as first 4
        return params[0], params[1], params[2], params[3]

    def _run_cli(self, args: list[str]) -> None:
        if not shutil.which(self.colmap_binary):
            raise RuntimeError(
                f"COLMAP binary '{self.colmap_binary}' not found on PATH. "
                "Install with: brew install colmap"
            )
        cmd = [self.colmap_binary] + args
        logger.debug(f"CLI: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"COLMAP CLI failed (exit {result.returncode}):\n{result.stdout}")
            raise RuntimeError(
                f"COLMAP CLI failed: {' '.join(args[:2])}\n{result.stdout[-2000:]}"
            )
        logger.debug(result.stdout[-1000:] if result.stdout else "")
