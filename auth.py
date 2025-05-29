from flask import request, jsonify
import jwt
from functools import wraps

SECRET_KEY = '8bf9485269a4ba37e6c37f918bf073932488be7a05a1bc3504aee4627b48aed1'

# Decorador para verificar token JWT
def token_requerido(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'Authorization' in request.headers:
            bearer = request.headers['Authorization']
            token = bearer.split(" ")[1] if " " in bearer else bearer

        if not token:
            return jsonify({'mensagem': 'Token ausente!'}), 401

        try:
            dados = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            request.usuario = dados  # salva os dados do token no request
        except jwt.ExpiredSignatureError:
            return jsonify({'mensagem': 'Token expirado!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'mensagem': 'Token inválido!'}), 401

        return f(*args, **kwargs)
    return decorated
