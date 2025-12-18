# CryoAtom + CryoSPARC Integration

This repository provides helper scripts to run [CryoAtom](https://github.com/YangLab-SDU/CryoAtom) from [CryoSPARC](https://cryosparc.com/) using [cryosparc-tools](https://github.com/cryoem-uoft/cryosparc-tools), and to copy the resulting atomic model back into the original CryoSPARC project/job.

Main features:

- Automatically locate the map volume from a CryoSPARC job
- Run CryoAtom `cryoatom build` with the selected map and FASTA sequence
- Optionally auto-select the least busy GPU
- Copy the final `out.cif` model back to the original CryoSPARC job directory
- (Optional) Run everything inside a CryoSPARC External Job

## Dependencies

- A working **CryoSPARC** installation (with license)
- Python environment with:
  - `cryosparc-tools` (see [tools.cryosparc.com](https://tools.cryosparc.com/))
- **CryoAtom** installed in a separate conda environment (see its README for details)

This project only provides thin integration scripts and does not bundle any part of CryoSPARC or CryoAtom.

## Installation

Clone this repository:

```bash
git clone https://github.com/XS-create/cryoatom-cryosparc-integration.git
cd cryoatom-cryosparc-integration
````

Install Python dependencies (in the same environment where you can import `cryosparc.tools`):

```bash
pip install -r requirements.txt
```

### Configure CryoSPARC connection

Set the following environment variables so that `cryosparc-tools` can connect to your CryoSPARC instance:

```bash
export CS_HOST=your_cryosparc_host      # default: 10.210.21.48
export CS_BASE_PORT=39000               # or your custom base port
export CS_EMAIL="your@email"
export CS_PASSWORD="your_password"
export CS_LICENSE_ID="your_license_id"
```

## Usage

### 1. Run CryoAtom from a CryoSPARC job (basic)

```bash
conda activate CryoAtom  # CryoAtom environment
python run_cryoatom.py \
  --project P164 \
  --job J243 \
  --volume-output volume \
  --fasta /path/to/seq.fasta \
  --gpu 0
```

This will:

1. Connect to CryoSPARC
2. Load the `volume` output from job `J243` of project `P164`
3. Automatically pick a map path field (e.g. `map_sharp/path` or `map/path`)
4. Copy the map and FASTA into a working directory like:
   `P164/cryoatom_P164_J243/`
5. Run `cryoatom build` and save results in `out/` under the working directory

Final outputs include:

* `out/out.cif`
* `out/out_raw.cif`

### 2. Auto-select GPU and copy result back to CryoSPARC job

```bash
conda activate CryoAtom
python run_cryoatom_auto.py \
  --project P164 \
  --job J44 \
  --fasta /path/to/seq.fasta
```

If `--gpu` is not specified, the script:

* Calls `nvidia-smi`
* Selects the least busy GPU (by memory usage ratio and utilization)
* Runs `run_cryoatom.py` with that GPU
* Copies the final `out.cif` to:

  `/<cryosparc_project_dir>/P164/J44/cryoatom/P164_J44_cryoatom.cif`

and appends a log message to the original CryoSPARC job.

You can also use the shell wrapper:

```bash
./run_cryoatom_auto.sh P164 J44 /path/to/seq.fasta
```

### 3. Use as a CryoSPARC External Job

1. Place `cryoatom_external_job.py` (and `run_cryoatom_auto.py`) in a location accessible to your CryoSPARC worker node.

2. Create an External Job in CryoSPARC and configure it to run:

   ```bash
   python cryoatom_external_job.py \
     --project P164 \
     --workspace W1 \
     --src-job J44 \
     --fasta /path/to/seq.fasta
   ```

3. The External Job will:

   * Invoke `run_cryoatom_auto.py`
   * Locate the resulting model (either in the job `cryoatom/` directory or in the working directory)
   * (Optionally) expose the model as a simple output dataset (see comments in the script)

## License

This project is released under the MIT License (see `LICENSE`).

It depends on:

* CryoAtom — MIT License
* cryosparc-tools — BSD-3-Clause License

You must comply with the licenses and terms of CryoSPARC and CryoAtom when using these scripts.

```

---

