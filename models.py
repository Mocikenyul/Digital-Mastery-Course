from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string
from datetime import datetime

db = SQLAlchemy()

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Siswa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(100), nullable=False)
    kelas_id = db.Column(db.Integer, db.ForeignKey('kelas.id'), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    username = db.Column(db.String(100), unique=True)  # = nama
    password_hash = db.Column(db.String(120))  # Random generated

    def generate_password(self):
        chars = string.ascii_letters + string.digits
        password = ''.join(random.choice(chars) for _ in range(8))
        self.password_hash = generate_password_hash(password)
        self.username = self.nama.lower().replace(' ', '_')
        return password  # Return plain password for display once

class Kelas(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_kelas = db.Column(db.String(50), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    biaya = db.Column(db.Float, nullable=False)
    kenaikan_kelas = db.Column(db.String(50))

class Jadwal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hari = db.Column(db.String(20), nullable=False)
    tanggal = db.Column(db.Date, nullable=False)
    kelas_id = db.Column(db.Integer, db.ForeignKey('kelas.id'), nullable=False)
    siswa_id = db.Column(db.Integer, db.ForeignKey('siswa.id'), nullable=False)
    materi = db.Column(db.String(200), nullable=False)
    siswa = db.relationship('Siswa', backref='jadwals', lazy='joined')  # Tambah ini untuk eager load

class Kehadiran(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    jadwal_id = db.Column(db.Integer, db.ForeignKey('jadwal.id'), nullable=False)
    siswa_id = db.Column(db.Integer, db.ForeignKey('siswa.id'), nullable=False)
    hadir = db.Column(db.Boolean, default=False)
    tanggal = db.Column(db.Date, default=datetime.utcnow)
    siswa = db.relationship('Siswa', backref='kehadirans', lazy='joined')  # Eager load siswa
    jadwal = db.relationship('Jadwal', backref='kehadirans', lazy='joined')  # Eager load jadwal

class Materi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_materi = db.Column(db.String(200), nullable=False)
    ketuntasan = db.Column(db.Float)  # Persentase
    hasil_ujian = db.Column(db.Float)
    siswa_id = db.Column(db.Integer, db.ForeignKey('siswa.id'), nullable=False)
    siswa = db.relationship('Siswa', backref='materis', lazy='joined')  # Tambah ini untuk eager load

class SaranKritik(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(100), nullable=False)
    pesan = db.Column(db.Text, nullable=False)
    tanggal = db.Column(db.Date, default=datetime.utcnow)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)

# Fungsi untuk hitung persentase kehadiran
def hitung_persentase_kehadiran(siswa_id):
    total_jadwal = Jadwal.query.filter_by(siswa_id=siswa_id).count()
    hadir = Kehadiran.query.filter_by(siswa_id=siswa_id, hadir=True).count()
    return (hadir / total_jadwal * 100) if total_jadwal > 0 else 0

# Hitung penghasilan bulanan
def hitung_penghasilan_bulanan(bulan, tahun):
    jadwal_bulan = Jadwal.query.filter(
        db.func.strftime('%m', Jadwal.tanggal) == f"{bulan:02d}",
        db.func.strftime('%Y', Jadwal.tanggal) == str(tahun)
    ).all()
    penghasilan = 0
    for j in jadwal_bulan:
        siswa = Siswa.query.get(j.siswa_id)
        if siswa:
            kelas = Kelas.query.get(siswa.kelas_id)
            if kelas:
                penghasilan += kelas.biaya
    return penghasilan