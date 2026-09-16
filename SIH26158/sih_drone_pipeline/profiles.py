from __future__ import annotations


PROFILES = {
    "manual": {},
    "verified-fast": {
        "quality": "draft",
        "keyframe_mode": "geometry",
        "keyframe_decode_mode": "sequential",
        "mapper": "pose-prior",
        # Frozen from the accepted full253_a3_robust_multimodel_1088 run.
        # Do not silently fold rejected dense-screen settings into this profile.
        "spatial_matching": False,
        "dense_frame_stride": 2,
        "dense_anchor_mode": "adaptive",
        "dense_target_references": None,
        "dense_source_images": 10,
        "dense_max_image_size": 1088,
        "dense_num_iterations": 4,
        "dense_num_samples": 15,
        "dense_window_step": 1,
        "delaunay_max_proj_dist": 20.0,
        "delaunay_num_threads": -1,
        "mapper_ba_gpu": True,
        "mapper_single_model": False,
        "mapper_no_extract_colors": True,
        "mapper_ba_global_frames_ratio": 1.4,
        "mapper_ba_global_points_ratio": 1.4,
        "mapper_ba_global_max_refinements": 2,
        "mapper_ba_global_ignore_redundant_points3d": True,
    },
    "high-detail": {
        "quality": "full",
        "keyframe_mode": "geometry",
        "keyframe_decode_mode": "sequential",
        "mapper": "pose-prior",
        "spatial_matching": True,
        "dense_anchor_mode": "adaptive",
        "dense_source_images": 16,
        "dense_max_image_size": 1920,
        "dense_num_iterations": 5,
        "dense_num_samples": 15,
        "dense_window_step": 1,
    },
}


def apply_processing_profile(args) -> dict:
    """Apply an explicit reproducible profile and return the resolved settings."""
    profile = getattr(args, "profile", "manual")
    if profile not in PROFILES:
        raise ValueError(f"Unknown processing profile: {profile}")
    applied = {}
    for name, value in PROFILES[profile].items():
        setattr(args, name, value)
        applied[name] = value
    return {"name": profile, "applied": applied}


def resolve_adaptive_dense_settings(args, frame_count: int) -> dict:
    """Record how the verified profile derives dense references from registered views."""
    if getattr(args, "profile", "manual") != "verified-fast":
        return {"automatic": False}
    return {
        "automatic": False,
        "input_frames": frame_count,
        "dense_target_references": args.dense_target_references,
        "reference_policy": "adaptive_stride",
        "dense_frame_stride": args.dense_frame_stride,
        "dense_source_images": args.dense_source_images,
        "dense_max_image_size": args.dense_max_image_size,
        "dense_num_iterations": args.dense_num_iterations,
        "dense_num_samples": args.dense_num_samples,
        "dense_window_step": args.dense_window_step,
    }
