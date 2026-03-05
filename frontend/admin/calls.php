<?php
require_once 'auth.php';
require_once 'config.php';
checkLogin();

$calls = $pdo->query("SELECT * FROM calls ORDER BY started_at DESC")->fetchAll();
?>
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Aramalar | Yaban Mercini Admin</title>
    <link rel="stylesheet" href="style.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body>
    <nav class="sidebar">
        <div class="logo">Yaban Mercini <span>Admin</span></div>
        <ul>
            <li onclick="location.href='index.php'">Dashboard</li>
            <li class="active" onclick="location.href='calls.php'">Aramalar</li>
            <li><a href="/phpmyadmin/" target="_blank">phpMyAdmin</a></li>
            <li style="margin-top: 2rem; color: #ff6b6b;" onclick="location.href='logout.php'">Çıkış Yap</li>
        </ul>
    </nav>

    <main class="content">
        <h1>Tüm Aramalar</h1>
        
        <table class="calls-table">
            <thead>
                <tr>
                    <th>Tarih</th>
                    <th>Numara</th>
                    <th>Sonuç</th>
                    <th>Süre</th>
                    <th>İşlem</th>
                </tr>
            </thead>
            <tbody>
                <?php foreach ($calls as $call): ?>
                <tr>
                    <td><?php echo date('d.m.Y H:i', strtotime($call['started_at'])); ?></td>
                    <td><?php echo $call['phone_number']; ?></td>
                    <td><span class="badge <?php echo $call['result']; ?>"><?php echo $call['result']; ?></span></td>
                    <td><?php echo $call['duration']; ?>s</td>
                    <td><button class="btn-view" onclick="location.href='detail.php?id=<?php echo $call['id']; ?>'">Detay</button></td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </main>
</body>
</html>
