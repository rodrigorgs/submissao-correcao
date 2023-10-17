class Robot {
  angle = 0
  position = { x: 0, y: 0 }
}

class CleaningModel {
  robot = new Robot()

  goalPosition = null
  changeListeners = []

  constructor(data) {
    const map = data["map"]
    if (map) {
      this.map = map.map((line, _) => line.split(""))
      for (let tx = 0; tx < 10; tx++) {
        for (let ty = 0; ty < 8; ty++) {
          if (this.map[ty][tx] == "r") {
            this.robot.position.x = tx
            this.robot.position.y = ty
            this.map[ty][tx] = "."
          } else if (this.map[ty][tx] == "!") {
            this.goalPosition = { x: tx, y: ty }
            this.map[ty][tx] = "."
          }
        }
      }
    }
  }

  addChangeListener(listener) {
    this.changeListeners.push(listener)
  }

  removeChangeListener(listener) {
    const index = this.changeListeners.indexOf(listener)
    if (index > -1) {
      this.changeListeners.splice(index, 1)
    }
  }

  changeCell(x, y, newValue) {
    const oldValue = this.map[y][x]
    if (newValue != oldValue) {
      this.map[y][x] = newValue
      for (let listener of this.changeListeners) {
        listener(x, y, oldValue, newValue)
      }
    }
  }

  getHeadingDirection(deltaAngle = 0) {
    const headingAngle = this.robot.angle + deltaAngle
    const radians = (headingAngle * Math.PI) / 180

    const direction = {
      x: Math.trunc(Math.cos(radians)),
      y: Math.trunc(Math.sin(radians))
    }
    return direction
  }

  moveRobotAngle(angle) {
    this.robot.angle = angle
    const direction = this.getHeadingDirection()

    const tx = this.robot.position.x + direction.x
    const ty = this.robot.position.y + direction.y

    if (tx < 0 || tx >= 10 || ty < 0 || ty >= 8) {
      return false
    }
    if (this.map[ty][tx] == "x") {
      return false
    }

    this.robot.position.x = tx
    this.robot.position.y = ty

    if (this.map[ty][tx] == "d") {
      this.changeCell(tx, ty, ".")
    }
    return true
  }

  turnRobot(deltaAngle) {
    this.robot.angle += deltaAngle
    this.robot.angle %= 360
  }

  moveRobotForward(steps = 1) {
    for (let i = 0; i < steps; i++) {
      this.moveRobotAngle(this.robot.angle)
    }
  }

  isFloorClean() {
    return this.map.join("").indexOf("d") == -1
  }

  hasGoalPosition() {
    return this.goalPosition != null
  }

  hasRobotReachedGoalPosition() {
    if (!this.goalPosition) {
      return false
    }
    return (
      this.robot.position.x == this.goalPosition.x &&
      this.robot.position.y == this.goalPosition.y
    )
  }

  hasObstacleAtDirection(directionString) {
    let deltaAngle = 0
    if (directionString == "LEFT") {
      deltaAngle -= 90
    } else if (directionString == "RIGHT") {
      deltaAngle += 90
    }
    const direction = this.getHeadingDirection(deltaAngle)

    const tx = this.robot.position.x + direction.x
    const ty = this.robot.position.y + direction.y

    if (tx < 0 || tx >= 10 || ty < 0 || ty >= 8) {
      return true
    }

    return this.map[ty][tx] == "x"
  }

  outcome() {
    if (!this.isFloorClean()) {
      return {
        successful: false,
        message: "Ainda há sujeira no chão!"
      }
    } else if (this.hasGoalPosition() && !this.hasRobotReachedGoalPosition()) {
      return {
        successful: false,
        message: "O robô não está no destino!"
      }
    } else {
      return {
        successful: true,
        message: "Parabéns, você concluiu o desafio!"
      }
    }
  }

  // methods added for compatibility with CleaningRobotStageManager
  moveDirection(direction) {
    if (direction == "LEFT") {
      this.moveRobotAngle(180)
    } else if (direction == "RIGHT") {
      this.moveRobotAngle(0)
    } else if (direction == "UP") {
      this.moveRobotAngle(270)
    } else if (direction == "DOWN") {
      this.moveRobotAngle(90)
    }
  }

  moveForward(steps = 1) {
    this.moveRobotForward(steps)
  }

  turn(angle) {
    this.turnRobot(angle)
  }
}
