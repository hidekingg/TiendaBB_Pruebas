Para inicializar la aplicacion en local, usa los siguientes comandos:

ANTES DE CUALQUIER COSA:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

y luego:
.\venv\Scripts\activate

Terminal de Tailwind: python manage.py tailwind start

Terminal de Django: python manage.py runserver
python manage.py runserver 0.0.0.0:8000

Ahora entra a http://127.0.0.1:8000

Si el servidor de PorgestSQL falla o no quiere conectar:
1. Presiona Tecla Windows + R, escribe services.msc y presiona Enter.
2. Busca el servicio llamado postgresql-x64-16 (el número puede variar según tu versión).
3. Asegúrate de que su estado sea "En ejecución". Si no lo está, haz clic derecho sobre él y selecciona "Iniciar"