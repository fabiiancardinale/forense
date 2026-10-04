"""Run separately: python -m evidex.inspection.worker --dir casos."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from evidex.inspection.jobs import Jobs

def run_one(workdir, timeout=120):
    jobs = Jobs(workdir)
    job = jobs.claim()
    if not job:
        return False
    folder = jobs.root/job['id']
    result = {'verdict':'inconclusive','summary':'El proceso falló o excedió su límite de tiempo.'}
    status = 'failed'
    try:
        if hashlib.sha256((folder/"original").read_bytes()).hexdigest() != job["sha256"]:
            raise ValueError("Stored file integrity mismatch")
        config = {}
        if job['consent']:
            settings = Path(workdir)/'config.json'
            cfg = json.loads(settings.read_text()) if settings.exists() else {}
            if cfg.get('sightengine_user') and cfg.get('sightengine_secret'):
                config = {k:cfg[k] for k in ('sightengine_user','sightengine_secret')}
                config['external_ai'] = True
        payload = {'path':str(folder/'original'), 'name':job['name'], 'output':str(folder), 'config':config}
        env = {**os.environ, 'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1'}
        proc = subprocess.run([sys.executable,'-m','evidex.inspection.runner'], input=json.dumps(payload),
                              text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=timeout, env=env, cwd=Path(__file__).resolve().parents[2])
        if proc.returncode == 0:
            result = json.loads((folder/'result.json').read_text())
            status = result['processing_status']
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    jobs.finish(job['id'], job['lease'], status, result)
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir',type=Path,default=Path('casos'))
    parser.add_argument('--once',action='store_true')
    args = parser.parse_args()
    while True:
        busy = run_one(args.dir.resolve())
        if args.once:
            break
        if not busy:
            time.sleep(2)

if __name__ == '__main__':
    main()
