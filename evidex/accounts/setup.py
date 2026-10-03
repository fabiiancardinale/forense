"""Local-only administrator initialization and password recovery."""
import argparse
import getpass
from pathlib import Path
from evidex.accounts.users import Store

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dir', default='casos')
    p.add_argument('--reset', action='store_true', help='Restablecer un administrador existente y revocar sus sesiones')
    a = p.parse_args()
    work = Path(a.dir).resolve(); work.mkdir(parents=True, exist_ok=True)
    store = Store(work)
    if store.all() and not a.reset:
        p.error('Ya existen usuarios; use --reset para recuperar un administrador.')
    username = input('Usuario administrador: ').strip().lower()
    if a.reset and (store.get(username) or {}).get('role') != 'administrador':
        p.error('Solo puede recuperar un administrador existente.')
    password = getpass.getpass('Contraseña (mínimo 15 caracteres): ')
    if password != getpass.getpass('Repita la contraseña: '):
        p.error('Las contraseñas no coinciden.')
    if error := store.add(username, username, 'administrador', password):
        p.error(error)
    store.log(username, 'recuperacion' if a.reset else 'instalacion')
    print('Administrador guardado. Las sesiones anteriores quedaron invalidadas.')

if __name__ == '__main__':
    main()
