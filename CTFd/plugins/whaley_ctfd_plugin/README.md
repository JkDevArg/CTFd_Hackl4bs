# Whaley CTFd Plugin

Integra Whaley con CTFd para que los participantes puedan lanzar instancias Docker
directamente desde el modal del reto.

## Instalación

1. Copia la carpeta `whaley_ctfd_plugin` dentro de `CTFd/plugins/`
2. Configura las variables de entorno en tu `docker-compose.yml` de CTFd:

```yaml
environment:
  - WHALEY_URL=http://host.docker.internal:8001   # o la IP de tu servidor
  - WHALEY_ADMIN_KEY=tu-clave-admin
```

3. Reinicia CTFd:
```bash
docker compose restart ctfd
```

## Cómo funciona

1. El plugin agrega rutas Flask en CTFd:
   - `POST /api/whaley/spawn`  → lanza instancia en Whaley
   - `GET  /api/whaley/status/<id>` → consulta si hay instancia activa
   - `POST /api/whaley/stop`   → detiene la instancia

2. El JS (`whaley.js`) se inyecta en todas las páginas y detecta cuando
   se abre el modal de un challenge, añadiendo el panel de control de instancia.

3. El backend de CTFd actúa como proxy hacia Whaley, usando el Access Token
   del usuario para autenticar contra Whaley/CTFd.

## Variables de entorno

| Variable          | Default                  | Descripción                        |
|-------------------|--------------------------|------------------------------------|
| `WHALEY_URL`      | `http://localhost:8001`  | URL donde corre Whaley             |
| `WHALEY_ADMIN_KEY`| `""`                     | Clave admin de Whaley (si aplica)  |

## Requisitos

- CTFd 3.x
- Whaley corriendo y accesible desde el contenedor de CTFd
- Los usuarios deben tener un Access Token generado en CTFd (Settings → Access Tokens)
