# Discord Notify — CTFd Plugin

Plugin para CTFd que notifica en Discord cuando alguien resuelve un reto o consigue el **First Blood**.

## Características

- 🩸 **First Blood**: Detecta automáticamente el primer solve de cada reto y anuncia `@here` en Discord con un embed rojo sangre.
- ✅ **Notificación de Solves**: Anuncia cada solve con nombre del solver, equipo (si aplica), categoría, puntos y número de solve.
- ⚙️ **Panel de Admin**: Configurable desde `/admin/discord` → menú "Plugins" en el panel de administración de CTFd.
- 🧪 **Test integrado**: Botón para verificar los webhooks sin necesidad de resolver un reto.
- 🔄 **No bloqueante**: Las llamadas a Discord se hacen en hilos en segundo plano.

## Instalación

1. Copia la carpeta `discord_notify` dentro de `CTFd/plugins/`.
2. Reinicia CTFd.
3. Ve al panel de Admin → **Plugins** → **Discord Notify 🎯**.

## Configuración

| Campo | Descripción |
|---|---|
| **Webhook Solves** | URL del webhook de Discord para anunciar todos los solves |
| **Webhook First Blood** | URL del webhook de Discord para anunciar first bloods (puede ser el mismo) |
| **Nombre del CTF** | Aparece en el footer de los embeds |
| **Footer** | Texto libre para el footer de los embeds |

## Cómo crear un Webhook en Discord

1. En tu servidor de Discord, ve al canal deseado → **Editar Canal**.
2. Pestaña **Integraciones** → **Webhooks** → **Nuevo Webhook**.
3. Dale un nombre (ej. "CTFd Solves") y copia la **URL del Webhook**.
4. Pégala en la configuración del plugin.

## Funcionamiento Técnico

El plugin utiliza un **monkey-patch** sobre el método `solve()` de todos los `BaseChallenge` registrados en CTFd. Esto garantiza que la notificación se dispara independientemente del tipo de reto (standard, dynamic, etc.).

El **first blood** se detecta comprobando si `Solves.count(challenge_id) == 0` **antes** de que se persista el solve actual, lo que garantiza precisión absoluta.
