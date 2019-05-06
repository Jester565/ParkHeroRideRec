import Accel_pb2
import matplotlib.pyplot as plt
from matplotlib.widgets import SpanSelector
import math
import os.path
import boto3
import botocore
from functools import partial

BUCKET_NAME = 'disneyapp3'
s3 = boto3.resource('s3')

TimePoints = []

MAX_DIST = 10

MAX_POINT_DIFF = 20

ACCEL_STEP = 1

def getArrTransitions(smartAvgs):
    transitions = []
    lastVal = 0
    for idx, val in enumerate(smartAvgs):
        if val != lastVal:
            transitions.append(idx)
            lastVal = val
    return transitions

def smartAverage(millisArr, accelArrs, millisInterval, millisWindowSize, signChangeLimit, limit):
    window = []
    signChangeWindow = []
    for idx, val in enumerate(accelArrs):
        window.append(0)
        signChangeWindow.append(0)

    smartAvgs = []
    startI = 0
    endI = 0
    currentMillis = millisArr[0]
    while True:
        currentMillis += millisWindowSize / 2
        print(currentMillis)
        while (millisArr[startI] < currentMillis - millisWindowSize / 2):
            for idx, arr in enumerate(accelArrs):
                window[idx] -= arr[startI]
                if startI > 0 and arr[startI] * arr[startI - 1] < 0:
                    signChangeWindow[idx] -= 1
            startI += 1
        while (millisArr[endI] < currentMillis + millisWindowSize / 2):
            for idx, arr in enumerate(accelArrs):
                window[idx] += arr[endI]
                if endI > 0 and arr[endI] * arr[endI - 1] < 0:
                    signChangeWindow[idx] += 1
            endI += 1
            if (endI >= len(millisArr)):
                return smartAvgs
        avgSum = 0
        for idx, val in enumerate(window):
            val = val / (endI - startI + 1)
            if signChangeWindow[idx] <= signChangeLimit:
                avgSum += val * val
        if math.sqrt(avgSum) >= limit:
            smartAvgs.append(1)
        else:
            smartAvgs.append(0)

def onTimePointAdded(smartAvgs, xMin, xMax):
    name = input("Enter TimePoint Name: ")
    timePointSmartAvgs = smartAvgs[int(xMin):int(xMax)]
    timePoint = {
          "name": name,
          "smartAvgs": timePointSmartAvgs,
          "xMin": int(xMin),
          "xMax": int(xMax)
    }
    TimePoints.append(timePoint)

def packify(rideName, timePoints):
    ridePacks = Accel_pb2.RidePacks()
    if os.path.isfile('packs'):
        packFile = open('packs', 'rb')
        raw = packFile.read()
        ridePacks.ParseFromString(raw)
        for packIdx, rp in enumerate(ridePacks.packs):
            if (rp.name == rideName):
                del ridePacks.packs[packIdx]
        packFile.close()

    ridePack = ridePacks.packs.add()
    lastXMax = -1
    for timePoint in timePoints:
         point = ridePack.points.add()
         point.name = timePoint["name"]
         point.transitions.extend(getArrTransitions(timePoint["smartAvgs"]))
         point.duration = int(timePoint["xMax"] - timePoint["xMin"])
         if lastXMax > 0:
             point.dist = int(timePoint["xMin"] - lastXMax)
         lastXMax = timePoint["xMax"]
    ridePack.name = rideName
    ridePack.duration = int(timePoints[len(timePoints) - 1]["xMax"] - timePoints[0]["xMin"])

    print("RidePack Contains")
    for rp in ridePacks.packs:
        print(rp.name)
    packFileWrite = open('packs', 'wb')
    packFileWrite.write(ridePacks.SerializeToString())
    packFileWrite.close()

def getMinAccel(accels, accelStartI, maxAccelI, ridePoints, accelStep, distMap):
    minDist = None
    minMatches = None
    targetAccelI = accelStartI
    transitionI = 0
    while True:
        if targetAccelI > maxAccelI:
            break
        #Keep incrementing transitionI until the accelerationI matches the target
        while True:
            if transitionI >= len(accels) or accels[transitionI] >= targetAccelI:
                break
            transitionI += 1
        distance = 0
        matches = [targetAccelI]
        distKey = ridePoints[0].name + str(targetAccelI)
        if distKey not in distMap:
            distance = getAccelsDistanceFromTimePoint(accels, ridePoints[0].transitions, targetAccelI, transitionI)
            if len(ridePoints) > 1:
                minDistResult = getMinAccel(accels, targetAccelI + ridePoints[0].duration + ridePoints[1].dist - MAX_POINT_DIFF, targetAccelI + ridePoints[0].duration + ridePoints[1].dist + MAX_POINT_DIFF, ridePoints[1:], accelStep, distMap)
                distance += minDistResult["distance"]
                matches += minDistResult["matches"]
            distMap[distKey] = { 
                "distance": distance, 
                "matches": matches
            }
        else:
            minDistResult = distMap[distKey]
            distance = minDistResult["distance"]
            matches = minDistResult["matches"]
        if minDist is None or distance < minDist:
            minDist = distance
            minMatches = matches
        #Move accelI to next target
        targetAccelI += accelStep
    return {
        "distance": minDist,
        "matches": minMatches
    }

def getAccelsDistanceFromTimePoint(accels, rideAccels, accelStartI, transitionStartI):
    accelI = 0
    rideI = 0
    distance = 0
    lastDistHigh = False
    while True:
        initialRideI = rideI
        #Run through ride points if accel array has ended or 
        while rideI < len(rideAccels) and (accelI + transitionStartI >= len(accels) or rideAccels[rideI] < accels[accelI + transitionStartI] - accelStartI):
            distanceResult = getArrDistance(accels, rideAccels, accelI + transitionStartI, rideI, accelStartI, 0)
            lastDistHigh = distanceResult["high"]
            distance += distanceResult["distance"]
            rideI += 1
        if rideI >= len(rideAccels):
            break
        distanceResult = getArrDistance(rideAccels, accels, rideI, accelI + transitionStartI, 0, accelStartI)
        lastDistHigh = distanceResult["high"]
        distance += distanceResult["distance"]
        accelI += 1
    return distance

def getArrDistance(bigArr, subArr, highI, midI, bigOff = 0, subOff = 0, blockLow = False, blockHigh = False):
    lowDist = MAX_DIST
    highDist = MAX_DIST
    if highI > 0 and highI <= len(bigArr) and midI < len(subArr):
        lowDist = (subArr[midI] - subOff) - (bigArr[highI - 1] - bigOff)
    if highI >= 0 and highI < len(bigArr) and midI < len(subArr):
        highDist = (bigArr[highI] - bigOff) - (subArr[midI] - subOff)
    minDist = 0
    if not blockLow and not blockHigh:
        minDist = min(lowDist, highDist)
    elif not blockLow:
        minDist = lowDist
    elif not blockHigh:
        minDist = highDist
    return {
        "high": minDist == highDist,
        "distance": calcDistance(minDist)
    }

def calcDistance(dist):
    if dist < MAX_DIST:
        return dist
    else:
        return MAX_DIST

def onRecognize(smartAverages, xMin, xMax):
    smartAvgs = smartAverages[int(xMin):int(xMax)]
    accels = getArrTransitions(smartAvgs)
    ridePacks = Accel_pb2.RidePacks()
    packFile = open('packs', 'rb')
    raw = packFile.read()
    ridePacks.ParseFromString(raw)
    minDist = None
    minName = None
    minMatches = None
    packs = []
    distMap = {}
    for packIdx, rp in enumerate(ridePacks.packs):
        accelResult = getMinAccel(accels, 0, len(smartAvgs) - rp.duration, rp.points, ACCEL_STEP, distMap)
        if minDist is None or accelResult["distance"] < minDist:
            minDist = accelResult["distance"]
            minName = rp.name
            minMatches = accelResult["matches"]
    packFile.close()
    modMinMatches = []
    for minMatch in minMatches:
        modMinMatches.append(int(minMatch + xMin))
    print("REC: ", minName, " -- ", minDist, " -- ", modMinMatches)

def main():
    mode = input("Enter mode (f/r)")
    while True:
        millisInterval = 30
        rideName = input("Enter accelfile: ")
        accelFileName = 'accels/' + rideName + '.accel'
        if not os.path.exists('accels'):
            os.makedirs('accels')
        if not os.path.isfile(accelFileName):
            s3.Bucket(BUCKET_NAME).download_file('rideAccels/' + rideName, accelFileName)
        with open(accelFileName, 'rb') as accelFile:
            raw = accelFile.read()
            accelData = Accel_pb2.AccelerationData()
            accelData.ParseFromString(raw)
            smartAvgs = smartAverage(accelData.millis, [accelData.x, accelData.y, accelData.z], millisInterval, 800, 3, 10000)
            smartAvgsMagnitude = []
            evenMillisArr = []
            for idx, val in enumerate(smartAvgs):
                evenMillisArr.append(idx)
            plt.title(rideName)
            plt.legend(loc='upper left')
            fig, (ax1, ax2) = plt.subplots(2, 1)
            ax1.plot(evenMillisArr, smartAvgs, '-og', label='x')
            ax2.plot(accelData.millis, accelData.x)
            ax2.plot(accelData.millis, accelData.y)
            ax2.plot(accelData.millis, accelData.z)
            if mode == "f":
                span = SpanSelector(ax1, partial(onTimePointAdded, smartAvgs), 'horizontal', useblit=True, rectprops=dict(alpha=0.5, facecolor='red'))
            else:
                span = SpanSelector(ax1, partial(onRecognize, smartAvgs), 'horizontal', useblit=True, rectprops=dict(alpha=0.5, facecolor='blue'))
            plt.show()
            packName = input("Enter pack name: ")
            packify(packName, TimePoints)
main()