// MySQL pool — mirrors bopchipboard's db.js conventions so the merge is a
// no-op (at merge time, delete this file and require('../db') instead).
// Falls back to file storage (see lib/settings.js) when MYSQL_HOST is unset.

const mysql = require('mysql2/promise');
require('dotenv').config();

let pool = null;

if (process.env.MYSQL_HOST) {
  pool = mysql.createPool({
    host: process.env.MYSQL_HOST,
    user: process.env.MYSQL_USER,
    password: process.env.MYSQL_PASSWORD,
    database: process.env.MYSQL_DATABASE,
    ssl: {
      rejectUnauthorized: false
    },
    waitForConnections: true,
    connectionLimit: 10,
    queueLimit: 0
  });
}

module.exports = { pool };
