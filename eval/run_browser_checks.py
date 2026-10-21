"""격리된 임시 DB와 포트로 개선 전후 화면 테스트 실행."""
from pathlib import Path
import os
import subprocess
import sys
import shutil
import tarfile
import tempfile
import time
import httpx
root=Path(__file__).resolve().parent.parent
node=os.environ.get('NODE_BINARY') or shutil.which('node')
if not node: raise SystemExit('Node.js와 playwright 패키지가 필요합니다.')
processes=[]
with tempfile.TemporaryDirectory() as tmp:
 baseline=Path(tmp)/'baseline'; baseline.mkdir()
 archive=Path(tmp)/'baseline.tar'
 subprocess.run(['git','archive','--format=tar','-o',str(archive),'5c6b9a0'],cwd=root,check=True)
 with tarfile.open(archive) as t:t.extractall(baseline,filter='data')
 try:
  for source,port,options in [(root,8810,['--db',f'{tmp}/after.db']),
                              (baseline,8811,['--db',f'{tmp}/before.db']),
                              (root,8860,['--frontend-backend','http://127.0.0.1:8810']),
                              (baseline,8861,['--frontend-backend','http://127.0.0.1:8811'])]:
   processes.append(subprocess.Popen([sys.executable,str(root/'eval/serve_test_app.py'),'--root',str(source),'--port',str(port),*options],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE))
  for port in [8810,8811,8860,8861]:
   for _ in range(100):
    try:
     if httpx.get(f'http://127.0.0.1:{port}/health',timeout=1).is_success: break
    except httpx.HTTPError: pass
    time.sleep(.2)
   else: raise RuntimeError(f'port {port} not ready')
  subprocess.run([node,'eval/browser_checks.cjs'],cwd=root,env=os.environ.copy(),check=True,timeout=180)
 finally:
  for process in processes: process.terminate()
  for process in processes:
   try: process.wait(timeout=10)
   except subprocess.TimeoutExpired: process.kill();process.wait()
