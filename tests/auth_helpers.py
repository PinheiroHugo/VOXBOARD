"""Cuenta ficticia para que la suite ejercite rutas autenticadas, sin desactivar acceso."""


def authenticate_client(client):
    page = client.get('/crear-cuenta', follow_redirects=True)
    setup = 'Crear cuenta docente' in page.get_data(as_text=True)
    with client.session_transaction() as session:
        token = session['csrf_token']
    data = {'username': 'docente_prueba', 'password': 'ClavePrueba2026', 'csrf_token': token}
    if setup:
        data['password_confirmation'] = data['password']
    response = client.post('/crear-cuenta' if setup else '/iniciar-sesion', data=data)
    assert response.status_code == 302, response.get_data(as_text=True)
    with client.session_transaction() as session:
        client.environ_base['HTTP_X_CSRF_TOKEN'] = session['csrf_token']
    return client
