from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from models import db, Admin, Siswa, Kelas, Jadwal, Kehadiran, Materi, SaranKritik, Settings, hitung_persentase_kehadiran, hitung_penghasilan_bulanan
from config import Config
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
import pandas as pd
import io
import os
import json
import random
import string
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    admin = Admin.query.get(user_id)
    if admin:
        admin.is_admin = True
        return admin
    return Siswa.query.get(user_id)

# Load JSON untuk settings awal & simpan ke DB jika belum ada
with app.app_context():
    db.create_all()
    if not Admin.query.filter_by(username='admin').first():
        admin = Admin(username='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
    # Load JSON
    json_file = 'DMC_Full_Template_2025-11-09.json'
    if os.path.exists(json_file):
        with open(json_file, 'r') as f:
            data = json.load(f)
            settings = data['settings']
            for key, value in settings.items():
                existing = Settings.query.filter_by(key=key).first()
                if not existing:
                    new_setting = Settings(key=key, value=str(value))
                    db.session.add(new_setting)
            db.session.commit()

# Fungsi bantu load settings ke session untuk template
@app.before_request
def load_settings():
    if 'settings' not in session:
        settings = {s.key: s.value for s in Settings.query.all()}
        session['settings'] = settings

# Route Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            login_user(admin)
            return redirect('/admin')
        siswa = Siswa.query.filter_by(username=username).first()
        if siswa and check_password_hash(siswa.password_hash, password):
            login_user(siswa)
            return redirect('/publik/dashboard')
        flash('Login gagal!')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

# Admin Dashboard
@app.route('/admin')
@login_required
def admin_dashboard():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        flash('Akses ditolak!')
        return redirect('/login')
    bulan_sekarang = datetime.now().month
    tahun_sekarang = datetime.now().year
    total_siswa = Siswa.query.count()
    jadwal_minggu = Jadwal.query.filter(
        Jadwal.tanggal >= datetime.now().date(),
        Jadwal.tanggal < (datetime.now() + timedelta(days=7)).date()
    ).count()
    penghasilan = hitung_penghasilan_bulanan(bulan_sekarang, tahun_sekarang)
    pers_kehadiran = sum(hitung_persentase_kehadiran(s.id) for s in Siswa.query.all()) / total_siswa if total_siswa else 0
    ketuntasan = sum(m.ketuntasan or 0 for m in Materi.query.all()) / Materi.query.count() if Materi.query.count() else 0
    return render_template('admin/dashboard.html', 
                           total_siswa=total_siswa, jadwal_minggu=jadwal_minggu, 
                           penghasilan=penghasilan, pers_kehadiran=pers_kehadiran, ketuntasan=ketuntasan)

# CRUD Siswa
@app.route('/admin/siswa', methods=['GET', 'POST'])
@login_required
def admin_siswa():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if request.method == 'POST':
        nama = request.form['nama']
        kelas_id = request.form['kelas_id']
        level = request.form['level']
        siswa = Siswa(nama=nama, kelas_id=kelas_id, level=level)
        password = siswa.generate_password()
        db.session.add(siswa)
        db.session.commit()
        flash(f'Siswa ditambahkan! Username: {siswa.username}, Password: {password}')
    siswa_list = Siswa.query.all()
    kelas_list = Kelas.query.all()
    return render_template('admin/siswa.html', siswa=siswa_list, kelas=kelas_list)

@app.route('/admin/siswa/update/<int:id>', methods=['GET', 'POST'])
@login_required
def update_siswa(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    siswa = Siswa.query.get_or_404(id)
    if request.method == 'POST':
        siswa.nama = request.form['nama']
        siswa.kelas_id = request.form['kelas_id']
        siswa.level = request.form['level']
        db.session.commit()
        flash('Siswa diupdate!')
        return redirect('/admin/siswa')
    kelas_list = Kelas.query.all()
    return render_template('admin/siswa.html', siswa_edit=siswa, siswa=Siswa.query.all(), kelas=kelas_list)

@app.route('/admin/siswa/delete/<int:id>')
@login_required
def delete_siswa(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    siswa = Siswa.query.get_or_404(id)
    db.session.delete(siswa)
    db.session.commit()
    flash('Siswa dihapus!')
    return redirect('/admin/siswa')

@app.route('/admin/siswa/export')
@login_required
def export_siswa():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    df = pd.read_sql(Siswa.query.statement, db.session.bind)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name='siswa.xlsx', as_attachment=True)

@app.route('/admin/siswa/import', methods=['POST'])
@login_required
def import_siswa():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if 'file' not in request.files: return redirect('/admin/siswa')
    file = request.files['file']
    if file.filename == '': return redirect('/admin/siswa')
    df = pd.read_excel(file)
    for _, row in df.iterrows():
        siswa = Siswa(nama=row['nama'], kelas_id=row['kelas_id'], level=row['level'])
        siswa.generate_password()
        db.session.add(siswa)
    db.session.commit()
    flash('Import berhasil!')
    return redirect('/admin/siswa')

# CRUD Jadwal
@app.route('/admin/jadwal', methods=['GET', 'POST'])
@login_required
def admin_jadwal():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if request.method == 'POST':
        try:
            hari = request.form['hari']
            tanggal = datetime.strptime(request.form['tanggal'], '%Y-%m-%d').date()
            kelas_id = int(request.form['kelas_id'])
            siswa_id = int(request.form['siswa_id'])
            materi = request.form['materi']
            jadwal = Jadwal(hari=hari, tanggal=tanggal, kelas_id=kelas_id, siswa_id=siswa_id, materi=materi)
            db.session.add(jadwal)
            db.session.commit()
            flash('Jadwal ditambahkan!')
        except ValueError:
            flash('Format tanggal atau input invalid!')
    jadwal_list = Jadwal.query.options(joinedload(Jadwal.siswa)).all()
    siswa_list = Siswa.query.all()
    kelas_list = Kelas.query.all()
    return render_template('admin/jadwal.html', jadwal=jadwal_list, siswa=siswa_list, kelas=kelas_list)

@app.route('/admin/jadwal/update/<int:id>', methods=['GET', 'POST'])
@login_required
def update_jadwal(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    jadwal = Jadwal.query.get_or_404(id)
    if request.method == 'POST':
        try:
            jadwal.hari = request.form['hari']
            jadwal.tanggal = datetime.strptime(request.form['tanggal'], '%Y-%m-%d').date()
            jadwal.kelas_id = int(request.form['kelas_id'])
            jadwal.siswa_id = int(request.form['siswa_id'])
            jadwal.materi = request.form['materi']
            db.session.commit()
            flash('Jadwal diupdate!')
            return redirect('/admin/jadwal')
        except ValueError:
            flash('Format tanggal atau input invalid!')
    siswa_list = Siswa.query.all()
    kelas_list = Kelas.query.all()
    return render_template('admin/jadwal.html', jadwal_edit=jadwal, jadwal=Jadwal.query.all(), siswa=siswa_list, kelas=kelas_list)

@app.route('/admin/jadwal/delete/<int:id>')
@login_required
def delete_jadwal(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    jadwal = Jadwal.query.get_or_404(id)
    db.session.delete(jadwal)
    db.session.commit()
    flash('Jadwal dihapus!')
    return redirect('/admin/jadwal')

@app.route('/admin/jadwal/export')
@login_required
def export_jadwal():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    df = pd.read_sql(Jadwal.query.statement, db.session.bind)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name='jadwal.xlsx', as_attachment=True)

@app.route('/admin/jadwal/import', methods=['POST'])
@login_required
def import_jadwal():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if 'file' not in request.files: return redirect('/admin/jadwal')
    file = request.files['file']
    if file.filename == '': return redirect('/admin/jadwal')
    df = pd.read_excel(file)
    for _, row in df.iterrows():
        try:
            tanggal = datetime.strptime(row['tanggal'], '%Y-%m-%d').date()
            jadwal = Jadwal(hari=row['hari'], tanggal=tanggal, 
                            kelas_id=row['kelas_id'], siswa_id=row['siswa_id'], materi=row['materi'])
            db.session.add(jadwal)
        except:
            continue
    db.session.commit()
    flash('Import berhasil (row invalid dilewati)!')
    return redirect('/admin/jadwal')

# CRUD Kehadiran
@app.route('/admin/kehadiran', methods=['GET', 'POST'])
@login_required
def admin_kehadiran():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    search = request.args.get('search')
    query = Kehadiran.query.options(joinedload(Kehadiran.siswa), joinedload(Kehadiran.jadwal)).join(Siswa).join(Jadwal)
    if search:
        query = query.filter(Siswa.nama.ilike(f'%{search}%'))
    kehadiran_list = query.all()

# Compute percentages and create enhanced list
    enhanced_kehadiran = []
    for k in kehadiran_list:
        persentase = hitung_persentase_kehadiran(k.siswa_id)
        enhanced_kehadiran.append({
            'id': k.id,
            'siswa': k.siswa,
            'jadwal': k.jadwal,
            'hadir': k.hadir,
            'persentase': persentase,
            'tanggal': k.tanggal
        })

    siswa_list = Siswa.query.all()
    jadwal_list = Jadwal.query.all()
    return render_template('admin/kehadiran.html', kehadiran=enhanced_kehadiran, siswa=siswa_list, jadwal=jadwal_list)

@app.route('/admin/kehadiran/create', methods=['POST'])
@login_required
def create_kehadiran():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    jadwal_id = request.form['jadwal_id']
    siswa_id = request.form['siswa_id']
    hadir = request.form.get('hadir', False) == 'True'  # Checkbox atau select
    kehadiran = Kehadiran(jadwal_id=jadwal_id, siswa_id=siswa_id, hadir=hadir)
    db.session.add(kehadiran)
    db.session.commit()
    flash('Kehadiran ditambahkan!')
    return redirect('/admin/kehadiran')

@app.route('/admin/kehadiran/update/<int:id>', methods=['POST'])
@login_required
def update_kehadiran(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    kehadiran = Kehadiran.query.get_or_404(id)
    kehadiran.hadir = True
    db.session.commit()
    flash('Kehadiran diperbarui!')
    return redirect('/admin/kehadiran')

@app.route('/admin/kehadiran/delete/<int:id>')
@login_required
def delete_kehadiran(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    kehadiran = Kehadiran.query.get_or_404(id)
    db.session.delete(kehadiran)
    db.session.commit()
    flash('Kehadiran dihapus!')
    return redirect('/admin/kehadiran')

@app.route('/admin/kehadiran/export')
@login_required
def export_kehadiran():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    df = pd.read_sql(Kehadiran.query.statement, db.session.bind)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name='kehadiran.xlsx', as_attachment=True)

@app.route('/admin/kehadiran/import', methods=['POST'])
@login_required
def import_kehadiran():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if 'file' not in request.files: return redirect('/admin/kehadiran')
    file = request.files['file']
    if file.filename == '': return redirect('/admin/kehadiran')
    df = pd.read_excel(file)
    for _, row in df.iterrows():
        kehadiran = Kehadiran(jadwal_id=row['jadwal_id'], siswa_id=row['siswa_id'], hadir=row.get('hadir', False))
        db.session.add(kehadiran)
    db.session.commit()
    flash('Import berhasil!')
    return redirect('/admin/kehadiran')

# CRUD Kelas
@app.route('/admin/kelas', methods=['GET', 'POST'])
@login_required
def admin_kelas():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if request.method == 'POST':
        nama_kelas = request.form['nama_kelas']
        level = request.form['level']
        biaya = float(request.form['biaya'])
        kenaikan_kelas = request.form.get('kenaikan_kelas')
        kelas = Kelas(nama_kelas=nama_kelas, level=level, biaya=biaya, kenaikan_kelas=kenaikan_kelas)
        db.session.add(kelas)
        db.session.commit()
        flash('Kelas ditambahkan!')
    kelas_list = Kelas.query.all()
    return render_template('admin/kelas.html', kelas=kelas_list)

@app.route('/admin/kelas/update/<int:id>', methods=['GET', 'POST'])
@login_required
def update_kelas(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    kelas = Kelas.query.get_or_404(id)
    if request.method == 'POST':
        kelas.nama_kelas = request.form['nama_kelas']
        kelas.level = request.form['level']
        kelas.biaya = float(request.form['biaya'])
        kelas.kenaikan_kelas = request.form.get('kenaikan_kelas')
        db.session.commit()
        flash('Kelas diupdate!')
        return redirect('/admin/kelas')
    return render_template('admin/kelas.html', kelas_edit=kelas, kelas=Kelas.query.all())

@app.route('/admin/kelas/delete/<int:id>')
@login_required
def delete_kelas(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    kelas = Kelas.query.get_or_404(id)
    db.session.delete(kelas)
    db.session.commit()
    flash('Kelas dihapus!')
    return redirect('/admin/kelas')

@app.route('/admin/kelas/export')
@login_required
def export_kelas():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    df = pd.read_sql(Kelas.query.statement, db.session.bind)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name='kelas.xlsx', as_attachment=True)

@app.route('/admin/kelas/import', methods=['POST'])
@login_required
def import_kelas():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if 'file' not in request.files: return redirect('/admin/kelas')
    file = request.files['file']
    if file.filename == '': return redirect('/admin/kelas')
    df = pd.read_excel(file)
    for _, row in df.iterrows():
        kelas = Kelas(nama_kelas=row['nama_kelas'], level=row['level'], biaya=row['biaya'], kenaikan_kelas=row.get('kenaikan_kelas'))
        db.session.add(kelas)
    db.session.commit()
    flash('Import berhasil!')
    return redirect('/admin/kelas')

# CRUD Materi
@app.route('/admin/materi', methods=['GET', 'POST'])
@login_required
def admin_materi():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if request.method == 'POST':
        nama_materi = request.form['nama_materi']
        ketuntasan = float(request.form.get('ketuntasan', 0))
        hasil_ujian = float(request.form.get('hasil_ujian', 0))
        siswa_id = int(request.form['siswa_id'])
        materi = Materi(nama_materi=nama_materi, ketuntasan=ketuntasan, hasil_ujian=hasil_ujian, siswa_id=siswa_id)
        db.session.add(materi)
        db.session.commit()
        flash('Materi ditambahkan!')
    materi_list = Materi.query.options(joinedload(Materi.siswa)).all()
    siswa_list = Siswa.query.all()
    return render_template('admin/materi.html', materi=materi_list, siswa=siswa_list)

@app.route('/admin/materi/update/<int:id>', methods=['GET', 'POST'])
@login_required
def update_materi(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    materi = Materi.query.get_or_404(id)
    if request.method == 'POST':
        materi.nama_materi = request.form['nama_materi']
        materi.ketuntasan = float(request.form.get('ketuntasan', 0))
        materi.hasil_ujian = float(request.form.get('hasil_ujian', 0))
        materi.siswa_id = int(request.form['siswa_id'])
        db.session.commit()
        flash('Materi diupdate!')
        return redirect('/admin/materi')
    siswa_list = Siswa.query.all()
    return render_template('admin/materi.html', materi_edit=materi, materi=Materi.query.all(), siswa=siswa_list)

@app.route('/admin/materi/delete/<int:id>')
@login_required
def delete_materi(id):
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    materi = Materi.query.get_or_404(id)
    db.session.delete(materi)
    db.session.commit()
    flash('Materi dihapus!')
    return redirect('/admin/materi')

@app.route('/admin/materi/export')
@login_required
def export_materi():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    df = pd.read_sql(Materi.query.statement, db.session.bind)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name='materi.xlsx', as_attachment=True)

@app.route('/admin/materi/import', methods=['POST'])
@login_required
def import_materi():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if 'file' not in request.files: return redirect('/admin/materi')
    file = request.files['file']
    if file.filename == '': return redirect('/admin/materi')
    df = pd.read_excel(file)
    for _, row in df.iterrows():
        materi = Materi(nama_materi=row['nama_materi'], ketuntasan=row.get('ketuntasan', 0), hasil_ujian=row.get('hasil_ujian', 0), siswa_id=row['siswa_id'])
        db.session.add(materi)
    db.session.commit()
    flash('Import berhasil!')
    return redirect('/admin/materi')

# Pengaturan
@app.route('/admin/pengaturan', methods=['GET', 'POST'])
@login_required
def admin_pengaturan():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        if new_password:
            current_user.set_password(new_password)
            db.session.commit()
            flash('Password diubah!')
    settings = session.get('settings', {})
    return render_template('admin/pengaturan.html', settings=settings)

@app.route('/admin/pengaturan/update', methods=['POST'])
@login_required
def update_pengaturan():
    if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
        return redirect('/login')
    for key in request.form:
        existing = Settings.query.filter_by(key=key).first()
        if existing:
            existing.value = request.form[key]
        else:
            new = Settings(key=key, value=request.form[key])
            db.session.add(new)
    db.session.commit()
    session.pop('settings', None)  # Reload session
    flash('Settings diupdate!')
    return redirect('/admin/pengaturan')

# Publik Dashboard
@app.route('/publik/dashboard')
@login_required
def publik_dashboard():
    if hasattr(current_user, 'is_admin') and current_user.is_admin:
        return redirect('/admin')
    total_siswa = Siswa.query.count()
    jadwal_minggu = Jadwal.query.filter_by(siswa_id=current_user.id).filter(
        Jadwal.tanggal >= datetime.now().date(),
        Jadwal.tanggal < (datetime.now() + timedelta(days=7)).date()
    ).count()
    pers_kehadiran = hitung_persentase_kehadiran(current_user.id)
    ketuntasan = sum(m.ketuntasan or 0 for m in Materi.query.filter_by(siswa_id=current_user.id)) / Materi.query.filter_by(siswa_id=current_user.id).count() if Materi.query.filter_by(siswa_id=current_user.id).count() else 0
    siswa_list = Siswa.query.all()
    kelas_list = Kelas.query.all()
    saran = SaranKritik.query.all()
    return render_template('publik/dashboard.html', 
                           total_siswa=total_siswa, jadwal_minggu=jadwal_minggu, 
                           pers_kehadiran=pers_kehadiran, ketuntasan=ketuntasan,
                           siswa=siswa_list, kelas=kelas_list, saran=saran)

@app.route('/publik/saran', methods=['POST'])
@login_required
def submit_saran():
    if hasattr(current_user, 'is_admin') and current_user.is_admin:
        return redirect('/admin')
    nama = request.form['nama']
    pesan = request.form['pesan']
    saran = SaranKritik(nama=nama, pesan=pesan)
    db.session.add(saran)
    db.session.commit()
    flash('Saran dikirim!')
    return redirect('/publik/dashboard')

# Route Utama
@app.route('/')
def index():
    return redirect('/login')

if __name__ == '__main__':
    app.run(debug=True)