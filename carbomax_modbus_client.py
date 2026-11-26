# carbomax_modbus_client.py
"""
Cliente Modbus RTU minimo (solo pyserial, sin pymodbus) para el CARBOMAX
DELTA por su conexion RS485 -> adaptador USB.

El equipo expone Modbus RTU Slave (manual del fabricante): direccion de
esclavo configurable 1-32, 8N1, velocidad 9600/19200/38400/57600. En esta
planta esta seteado en direccion 1, 57600 bps, sobre el adaptador USB-serie
que Windows monta en COM3 (chip CH340, USB\\VID_1A86&PID_55D3) -- ver
config.py y la memoria de sesion en fundicion_romero
(carbomax_delta_rs485.md).

Todavia no hay mapa de registros: este modulo no interpreta nada, solo
implementa las 4 funciones de lectura Modbus (01-04) tal como las expone
el equipo, para que la pestana "Delta Modbus" de la web vuelque los
valores crudos y alguien los identifique a mano contra una medicion
conocida en el instrumento.

Es el equivalente, para esta interfaz del equipo, de lo que
spectro_client.py es para el LMX06: hablar el protocolo real en vez de
depender de un archivo intermedio. No confundir con carbomax_emulator.py /
el Extractor decompilado: esos hablan la OTRA interfaz del mismo
fabricante, por red (CGI/HTTP), ya integrada aparte.
"""

import struct

import serial

from config import CARBOMAX_MODBUS_BAUDRATE, CARBOMAX_MODBUS_PORT, CARBOMAX_MODBUS_SLAVE_ID

READ_TIMEOUT = 1.0

# Limites del protocolo Modbus RTU (no del equipo): una sola lectura no
# puede pedir mas que esto por especificacion.
MAX_BIT_QUANTITY = 2000
MAX_REGISTER_QUANTITY = 125

_EXCEPTION_MESSAGES = {
    1: "Funcion ilegal",
    2: "Direccion de dato ilegal",
    3: "Valor de dato ilegal",
    4: "Falla en el dispositivo esclavo",
    5: "Confirmacion (processing)",
    6: "Esclavo ocupado",
    11: "Gateway: dispositivo de destino no responde",
}


class ModbusError(Exception):
    pass


def _crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _build_request(function_code, start_address, quantity, slave_id):
    frame = struct.pack(">BBHH", slave_id, function_code, start_address, quantity)
    return frame + struct.pack("<H", _crc16(frame))


def _open_serial(port, baudrate):
    return serial.Serial(
        port=port,
        baudrate=baudrate,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=READ_TIMEOUT,
    )


def _read_response(ser, function_code):
    header = ser.read(2)
    if len(header) < 2:
        raise ModbusError(
            "Sin respuesta del equipo (timeout) - verificar puerto/baudrate/direccion de esclavo."
        )
    resp_func = header[1]
    if resp_func & 0x80:
        rest = ser.read(3)
        if len(rest) < 3:
            raise ModbusError("Respuesta de excepcion incompleta.")
        exc_code = rest[0]
        msg = _EXCEPTION_MESSAGES.get(exc_code, f"codigo {exc_code}")
        raise ModbusError(f"El equipo respondio excepcion Modbus: {msg}")
    if resp_func != function_code:
        raise ModbusError(f"Funcion inesperada en la respuesta: {resp_func} (se esperaba {function_code})")
    byte_count_raw = ser.read(1)
    if len(byte_count_raw) < 1:
        raise ModbusError("Respuesta incompleta (sin byte count).")
    byte_count = byte_count_raw[0]
    payload = ser.read(byte_count)
    crc_bytes = ser.read(2)
    if len(payload) < byte_count or len(crc_bytes) < 2:
        raise ModbusError("Respuesta incompleta (datos o CRC truncados).")
    frame = header + byte_count_raw + payload
    expected_crc = _crc16(frame)
    received_crc = crc_bytes[0] | (crc_bytes[1] << 8)
    if expected_crc != received_crc:
        raise ModbusError("CRC invalido en la respuesta - ruido en el bus o baudrate incorrecto.")
    return payload


def _bits_from_payload(payload, quantity):
    bits = []
    for byte in payload:
        for i in range(8):
            bits.append(bool((byte >> i) & 1))
    return bits[:quantity]


def _registers_from_payload(payload):
    return list(struct.unpack(f">{len(payload) // 2}H", payload))


def _read(function_code, start_address, quantity, port, baudrate, slave_id, is_bits):
    ser = _open_serial(port, baudrate)
    try:
        ser.reset_input_buffer()
        ser.write(_build_request(function_code, start_address, quantity, slave_id))
        payload = _read_response(ser, function_code)
        return _bits_from_payload(payload, quantity) if is_bits else _registers_from_payload(payload)
    finally:
        ser.close()


def read_coils(start_address=0, quantity=16, port=None, baudrate=None, slave_id=None):
    return _read(1, start_address, quantity, port or CARBOMAX_MODBUS_PORT,
                 baudrate or CARBOMAX_MODBUS_BAUDRATE, slave_id or CARBOMAX_MODBUS_SLAVE_ID, is_bits=True)


def read_discrete_inputs(start_address=0, quantity=16, port=None, baudrate=None, slave_id=None):
    return _read(2, start_address, quantity, port or CARBOMAX_MODBUS_PORT,
                 baudrate or CARBOMAX_MODBUS_BAUDRATE, slave_id or CARBOMAX_MODBUS_SLAVE_ID, is_bits=True)


def read_holding_registers(start_address=0, quantity=16, port=None, baudrate=None, slave_id=None):
    return _read(3, start_address, quantity, port or CARBOMAX_MODBUS_PORT,
                 baudrate or CARBOMAX_MODBUS_BAUDRATE, slave_id or CARBOMAX_MODBUS_SLAVE_ID, is_bits=False)


def read_input_registers(start_address=0, quantity=16, port=None, baudrate=None, slave_id=None):
    return _read(4, start_address, quantity, port or CARBOMAX_MODBUS_PORT,
                 baudrate or CARBOMAX_MODBUS_BAUDRATE, slave_id or CARBOMAX_MODBUS_SLAVE_ID, is_bits=False)


# clave -> (funcion, lector, etiqueta tal como la nombra el manual del
# Carbomax Delta). El orden define el orden en que se listan en la web.
_FUNCTIONS = [
    ("coils", 1, read_coils, "01 Read Coils"),
    ("discrete_inputs", 2, read_discrete_inputs, "02 Read Discrete Input"),
    ("holding_registers", 3, read_holding_registers, "03 Read Holding Registers"),
    ("input_registers", 4, read_input_registers, "04 Read Input Registers"),
]


def leer_todo(start_address=0, quantity=20, port=None, baudrate=None, slave_id=None):
    """Corre las 4 funciones de lectura Modbus contra el equipo y devuelve
    {clave: {label, start, quantity, ok, values | error}} -- una entrada
    por funcion, cada una independiente: si una tira excepcion Modbus (ej.
    direccion invalida para esa funcion puntual) no aborta a las demas."""
    reg_quantity = max(1, min(int(quantity), MAX_REGISTER_QUANTITY))
    bit_quantity = max(1, min(int(quantity), MAX_BIT_QUANTITY))
    results = {}
    for key, func_code, reader, label in _FUNCTIONS:
        is_bits = func_code in (1, 2)
        qty = bit_quantity if is_bits else reg_quantity
        entry = {"label": label, "start": start_address, "quantity": qty}
        try:
            values = reader(start_address, qty, port=port, baudrate=baudrate, slave_id=slave_id)
            entry["ok"] = True
            if is_bits:
                entry["values"] = [
                    {"address": start_address + i, "value": int(v)} for i, v in enumerate(values)
                ]
            else:
                entry["values"] = [
                    {"address": start_address + i, "value": v, "hex": f"0x{v:04X}"}
                    for i, v in enumerate(values)
                ]
        except Exception as ex:
            entry["ok"] = False
            entry["error"] = str(ex)
        results[key] = entry
    return results


if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(json.dumps(leer_todo(start, count), ensure_ascii=False, indent=2))
