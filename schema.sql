CREATE DATABASE IF NOT EXISTS examregdb
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE examregdb;

CREATE TABLE IF NOT EXISTS users (
  id INT PRIMARY KEY AUTO_INCREMENT,
  email VARCHAR(255) UNIQUE NOT NULL,
  nshe  VARCHAR(10) NOT NULL,
  full_name VARCHAR(255) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('student','faculty') NOT NULL DEFAULT 'student',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_nshe (nshe)
) ENGINE=InnoDB;


-- EXAMS TABLE
CREATE TABLE IF NOT EXISTS exams (
  id INT AUTO_INCREMENT PRIMARY KEY,
  exam_code VARCHAR(255) UNIQUE NOT NULL,
  description VARCHAR(255)
) ENGINE=InnoDB;

-- LOCATIONS TABLE
CREATE TABLE IF NOT EXISTS locations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  campus_name ENUM('Henderson', 'Charleston', 'North Las Vegas') NOT NULL,
  building_name VARCHAR(255) NOT NULL,
  room_number VARCHAR(50) NOT NULL
) ENGINE=InnoDB;

-- EXAM SESSIONS TABLE
CREATE TABLE IF NOT EXISTS examsessions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  exam_id INT NOT NULL,
  session_datetime DATETIME NOT NULL,
  location_id INT NOT NULL,
  creator_id INT NOT NULL,
  proctor_id INT NOT NULL,
  capacity INT DEFAULT 20,
  FOREIGN KEY (exam_id) REFERENCES exams(id),
  FOREIGN KEY (location_id) REFERENCES locations(id),
  FOREIGN KEY (creator_id) REFERENCES users(id),
  FOREIGN KEY (proctor_id) REFERENCES users(id)
) ENGINE=InnoDB;

-- REGISTRATIONS TABLE
CREATE TABLE IF NOT EXISTS registrations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  session_id INT NOT NULL,
  user_id INT NOT NULL,
  registered_at DATETIME DEFAULT NOW(),
  cancelled BOOLEAN DEFAULT FALSE,
  cancelled_at DATETIME NULL,
  UNIQUE (user_id, session_id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (session_id) REFERENCES examsessions(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS appointments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  title VARCHAR(200) NOT NULL,
  starts_at DATETIME NOT NULL,
  ends_at DATETIME NOT NULL,
  location VARCHAR(200) DEFAULT NULL,
  notes TEXT DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user_time (user_id, starts_at),
  CONSTRAINT fk_appt_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

ALTER TABLE examsessions
  ADD COLUMN duration_minutes INT NOT NULL DEFAULT 90
  AFTER session_datetime;
