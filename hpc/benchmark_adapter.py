"""External benchmark adapter for running Imagent_J through Apptainer.

This shim deliberately lives in the Imagent_J repository. It extends the
benchmark's built-in ``AgenticJApptainerAdapter`` without modifying the
unpublished benchmark checkout.

Compared with the benchmark's current adapter it additionally:

* bind-mounts ``imagentj_config.yaml`` so model / VLM / QA changes do not
  require rebuilding the SIF;
* bind-mounts the optional MCP host configuration;
* enables NVIDIA GPU passthrough with Apptainer's ``--nv`` flag by default;
* defaults persistent Apptainer volumes to this repository's
  ``.apptainer/volumes`` directory; and
* defaults to unattended mode so concurrent HPC jobs do not collide on the
  fixed x11vnc / noVNC ports.

Load it with the benchmark CLI's dynamic adapter mechanism:

    --agent-class hpc.benchmark_adapter:ImagentJApptainerAdapter
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from bioimage_agent_bench.adapters.agentic_j_apptainer import (
    AgenticJApptainerAdapter,
)


_CONTAINER_CONFIG = "/app/imagentj_config.yaml"
_CONTAINER_MCP_CONFIG_DIR = "/app/.imagentj"
_REPO_ROOT = Path(__file__).resolve().parents[1]


class ImagentJApptainerAdapter(AgenticJApptainerAdapter):
    """Apptainer adapter with Imagent_J runtime config support.

    Parameters not documented here are passed through to the benchmark's
    :class:`AgenticJApptainerAdapter`.

    Parameters
    ----------
    config_path:
        Host runtime config to mount read-only at
        ``/app/imagentj_config.yaml``. Defaults to the config in this repo.
    mcp_config_dir:
        Optional host directory to mount read-only at ``/app/.imagentj``.
        Defaults to this repo's ``.imagentj`` directory when it exists.
    unattended:
        Skip x11vnc / noVNC while retaining Xvfb and the GUI framebuffer.
        Defaults to ``True`` for collision-free HPC batch jobs.
    nv:
        Pass ``--nv`` to Apptainer so the SIF can use host NVIDIA devices and
        driver libraries. Defaults to ``True`` for the GPU benchmark image.
    """

    def __init__(
        self,
        sif_path: Optional[str] = None,
        agent_dir: Optional[str] = None,
        volumes_dir: Optional[str] = None,
        apptainer_bin: str = "apptainer",
        overlay: Optional[str] = None,
        interactive: bool = False,
        timeout: int = 7200,
        agent_id: str = "agentic_j",
        config_path: Optional[str] = None,
        mcp_config_dir: Optional[str] = None,
        unattended: bool = True,
        nv: bool = True,
    ) -> None:
        resolved_agent_dir = Path(agent_dir).resolve() if agent_dir else _REPO_ROOT
        resolved_volumes = (
            Path(volumes_dir).resolve()
            if volumes_dir
            else resolved_agent_dir / ".apptainer" / "volumes"
        )
        resolved_config = (
            Path(config_path).resolve()
            if config_path
            else resolved_agent_dir / "imagentj_config.yaml"
        )
        if not resolved_config.is_file():
            raise FileNotFoundError(
                f"Imagent_J config not found: {resolved_config}"
            )

        if mcp_config_dir:
            resolved_mcp: Optional[Path] = Path(mcp_config_dir).resolve()
            if not resolved_mcp.is_dir():
                raise NotADirectoryError(
                    f"MCP config directory not found: {resolved_mcp}"
                )
        else:
            candidate = resolved_agent_dir / ".imagentj"
            resolved_mcp = candidate if candidate.is_dir() else None

        self._imagentj_config = resolved_config
        self._mcp_config_dir = resolved_mcp
        self._unattended = unattended
        self._nv = nv

        super().__init__(
            sif_path=sif_path,
            agent_dir=str(resolved_agent_dir),
            volumes_dir=str(resolved_volumes),
            apptainer_bin=apptainer_bin,
            overlay=overlay,
            interactive=interactive,
            timeout=timeout,
            agent_id=agent_id,
        )

    def _build_cmd(self, input_dir: Path, output_dir: Path) -> List[str]:
        cmd = super()._build_cmd(input_dir, output_dir)

        # All Apptainer options must precede the final positional SIF path.
        image = cmd.pop()
        if self._nv:
            cmd.append("--nv")
        cmd += [
            "--bind",
            f"{self._imagentj_config}:{_CONTAINER_CONFIG}:ro",
            "--env",
            f"IMAGENTJ_CONFIG={_CONTAINER_CONFIG}",
            "--env",
            f"IMAGENTJ_UNATTENDED={'true' if self._unattended else 'false'}",
        ]
        if self._mcp_config_dir is not None:
            cmd += [
                "--bind",
                f"{self._mcp_config_dir}:{_CONTAINER_MCP_CONFIG_DIR}:ro",
                "--env",
                f"IMAGENTJ_MCP_CONFIG={_CONTAINER_MCP_CONFIG_DIR}/mcp.json",
            ]
        cmd.append(image)
        return cmd
