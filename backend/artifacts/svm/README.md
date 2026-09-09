# Model klasifikasi intent

Letakkan model terlatih di `intent_classifier.pkl` dalam folder ini.
Backend memuatnya sekali saat startup melalui `config/settings.py`.
Lokasi dapat diganti dengan environment `INTENT_MODEL_PATH`.

Folder ini bukan aset publik dan tidak dipasang sebagai static URL.
Hanya gunakan artifact tepercaya karena pemuatan pickle dapat menjalankan kode.
File .pkl tetap diabaikan Git; sertakan artifact ini ketika menyiapkan mesin baru.

Dockerfile menyalin folder backend termasuk artifact ini saat build.
Compose juga memasang backend sebagai bind mount ke /app, sehingga lokasi
default di container adalah /app/artifacts/svm/intent_classifier.pkl.
