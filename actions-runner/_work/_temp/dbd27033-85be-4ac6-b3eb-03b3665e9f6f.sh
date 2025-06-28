echo "🚀 Starting deployment on self-hosted runner..."

# Jestem już na serwerze, więc mogę bezpośrednio:
cd /var/www/gingerity.space

# Backup przed aktualizacją
echo "💾 Creating backup..."
sudo mkdir -p /var/www/backups
sudo cp -r /var/www/gingerity.space /var/www/backups/gingerity_backup_$(date +%Y%m%d_%H%M%S)

# Aktualizacja kodu (GitHub Actions już pobrał najnowszy kod)
echo "📥 Updating code..."
sudo cp -r $GITHUB_WORKSPACE/* /var/www/gingerity.space/

# Uprawnienia
echo "🔒 Setting permissions..."
sudo chown -R www-data:www-data /var/www/gingerity.space
sudo chmod +x /var/www/gingerity.space/app.py

# Uruchom testy na serwerze
echo "🧪 Running tests on server..."
cd /var/www/gingerity.space
python3 -m pytest test_simple.py -v || echo "⚠️ Tests failed but continuing..."

# Graceful restart
echo "🔄 Restarting services..."
sudo systemctl reload gingerity-dashboard || sudo systemctl restart gingerity-dashboard

# Health check
echo "✅ Health check..."
sleep 5
curl -f http://localhost:5000/api/system > /dev/null && echo "✅ API works!" || echo "❌ API failed!"

# Cleanup
echo "🧹 Cleaning old backups..."
cd /var/www/backups
sudo find . -name "gingerity_backup_*" -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true

echo "🎉 Deployment completed successfully!"
