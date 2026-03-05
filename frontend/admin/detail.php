<?php
require_once 'auth.php';
require_once 'config.php';
checkLogin();

$id = $_GET['id'] ?? 0;
$stmt = $pdo->prepare("SELECT * FROM calls WHERE id = ?");
$stmt->execute([$id]);
$call = $stmt->fetch();

if (!$call) {
    die("Arama bulunamadı!");
}

$stmt = $pdo->prepare("SELECT * FROM transcripts WHERE call_id = ? ORDER BY created_at ASC");
$stmt->execute([$id]);
$transcript = $stmt->fetchAll();
?>
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Arama Detayı | Yaban Mercini Admin</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <nav class="sidebar">
        <div class="logo">Yaban Mercini <span>Admin</span></div>
        <ul>
            <li onclick="location.href='index.php'">Dashboard</li>
            <li onclick="location.href='calls.php'">Aramalar</li>
            <li><a href="/phpmyadmin/" target="_blank">phpMyAdmin</a></li>
            <li style="margin-top: 2rem; color: #ff6b6b;" onclick="location.href='logout.php'">Çıkış Yap</li>
        </ul>
    </nav>
    <main class="content">
        <a href="javascript:history.back()" style="color: var(--accent); text-decoration: none;">&lt; Geri Dön</a>
        <h1 style="margin-top: 1rem;">Arama Detayı</h1>
        <div class="stat-card" style="margin-bottom: 2rem;">
            <p style="font-size: 1.2rem;"><?php echo $call['phone_number']; ?> | <?php echo date('d.m.Y H:i', strtotime($call['started_at'])); ?> | <?php echo $call['duration']; ?>s</p>
        </div>

        <div class="transcript">
            <?php foreach ($transcript as $msg): ?>
            <div class="message <?php echo $msg['role']; ?>">
                <small style="opacity: 0.5;"><?php echo $msg['role'] === 'user' ? 'Kullanıcı' : 'Yaban Mercini'; ?></small><br>
                <?php echo htmlspecialchars($msg['content']); ?>
            </div>
            <?php endforeach; ?>
        </div>
    </main>
</body>
</html>
